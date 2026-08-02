import math
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel
from sqlalchemy.future import select
from jose import JWTError, jwt
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import (
    Restaurant, Order, OrderItem, OrderItemExclusion, OrderItemModifier,
    MenuItem, Category, ModifierOption, ModifierGroup, OrderStatus, FulfillmentMethod, Customer
)
from app.services.socket_manager import manager
from app.services.whatsapp import WhatsAppService
from app.services.order_service import OrderService

logger = logging.getLogger(__name__)
router = APIRouter()

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns distance in kilometers between two GPS points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class CartItemPayload(BaseModel):
    menu_item_id: int
    quantity: int
    exclusions: Optional[List[str]] = []
    modifier_option_ids: Optional[List[int]] = []

class CheckoutPayload(BaseModel):
    fulfillment_method: str  # "delivery" or "pickup"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    customer_name: Optional[str] = None
    customer_notes: Optional[str] = None
    items: List[CartItemPayload]

async def verify_session_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")

@router.post("/orders/checkout")
async def process_checkout(payload: CheckoutPayload, session_payload: dict = Depends(verify_session_token)):
    wa_id = session_payload.get("sub")
    restaurant_id = session_payload.get("rid")
    if not wa_id or not restaurant_id:
        raise HTTPException(status_code=401, detail="Invalid session claims")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart cannot be empty")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = res.scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # 1. Geo-Fencing & Delivery Fee Calculation
        delivery_fee = 0.0
        if payload.fulfillment_method == "delivery":
            if restaurant.latitude and restaurant.longitude and payload.latitude and payload.longitude:
                dist = calculate_haversine_distance(
                    restaurant.latitude, restaurant.longitude,
                    payload.latitude, payload.longitude
                )
                if dist > restaurant.max_delivery_radius_km:
                    raise HTTPException(status_code=400, detail=f"Location is outside our delivery radius (Max: {restaurant.max_delivery_radius_km} km)")
                
                delivery_fee = restaurant.base_delivery_fee + (dist * restaurant.per_km_delivery_fee)
            else:
                # If restaurant hasn't configured GPS, or client blocked GPS, fallback to base fee or reject.
                # Assuming base fee fallback if customer coords are missing.
                delivery_fee = restaurant.base_delivery_fee

        # 2. Server-side Pricing
        method = FulfillmentMethod.DELIVERY if payload.fulfillment_method == "delivery" else FulfillmentMethod.PICKUP
        
        new_order = Order(
            restaurant_id=restaurant_id,
            customer_wa_id=wa_id,
            fulfillment_method=method,
            status=OrderStatus.RECEIVED,
            total_price=0.0,
            delivery_fee=delivery_fee,
            latitude=payload.latitude,
            longitude=payload.longitude,
            customer_name=payload.customer_name,
            customer_notes=payload.customer_notes
        )
        db.add(new_order)
        await db.flush()

        item_total = 0.0
        for req_item in payload.items:
            if req_item.quantity < 1:
                raise HTTPException(status_code=400, detail="Item quantity must be at least 1")

            # Validate item ownership & price
            item_q = await db.execute(
                select(MenuItem)
                .join(Category)
                .where(MenuItem.id == req_item.menu_item_id, Category.restaurant_id == restaurant_id)
            )
            menu_item = item_q.scalar_one_or_none()
            if not menu_item or not menu_item.is_available:
                raise HTTPException(status_code=400, detail=f"Item {req_item.menu_item_id} is unavailable")

            order_line = OrderItem(
                order_id=new_order.id,
                menu_item_id=menu_item.id,
                quantity=req_item.quantity,
                unit_price=menu_item.price
            )
            db.add(order_line)
            await db.flush()
            
            line_price = menu_item.price

            # Exclusions
            for exc in req_item.exclusions:
                db.add(OrderItemExclusion(order_item_id=order_line.id, ingredient_name=exc))

            # Modifiers
            for mod_id in req_item.modifier_option_ids:
                mod_q = await db.execute(
                    select(ModifierOption)
                    .join(ModifierGroup)
                    .join(MenuItem, MenuItem.id == ModifierGroup.menu_item_id)
                    .join(Category)
                    .where(ModifierOption.id == mod_id, Category.restaurant_id == restaurant_id)
                )
                mod_opt = mod_q.scalar_one_or_none()
                if not mod_opt:
                    raise HTTPException(status_code=400, detail=f"Invalid modifier {mod_id}")
                
                db.add(OrderItemModifier(order_item_id=order_line.id, modifier_option_id=mod_id))
                line_price += mod_opt.price_override

            order_line.unit_price = line_price
            item_total += (line_price * req_item.quantity)

        # 3. Finalize Totals & Delivery PIN
        new_order.total_price = item_total + delivery_fee
        new_order.delivery_pin = await OrderService.generate_delivery_pin(db)
        
        # Enforce Grace Period
        if restaurant.wallet_balance <= -75.0:
            raise HTTPException(status_code=400, detail="ERROR_SCREEN")
            
        # Deduct from Prepaid Wallet
        from app.models import WalletTransaction, TransactionType
        restaurant.wallet_balance -= 3.0
        transaction = WalletTransaction(
            restaurant_id=restaurant_id,
            amount=-3.0,
            type=TransactionType.DEBIT,
            description=f"Order commission (Order #{new_order.id})"
        )
        db.add(transaction)
        
        await db.commit()
        await db.refresh(new_order)

        # 4. Trigger Notifications & WebSockets
        # Emit to KDS
        await manager.broadcast_to_restaurant(restaurant_id, {"event": "NEW_ORDER", "order_id": new_order.id})

        # Send confirmation WhatsApp message to customer
        cust_req = await db.execute(select(Customer.language).where(Customer.wa_id == wa_id))
        cust_lang = cust_req.scalar_one_or_none() or "fr"
        
        wa_service = WhatsAppService(token=restaurant.api_token, phone_id=restaurant.phone_number_id)
        
        await wa_service.send_order_confirmation(wa_id, cust_lang)
        await wa_service.notify_manager_new_order(restaurant.owner_wa_id, new_order.id, new_order.total_price, new_order.fulfillment_method.value)

        return {
            "success": True,
            "order_id": new_order.id,
            "total_price": new_order.total_price,
            "delivery_fee": new_order.delivery_fee
        }
