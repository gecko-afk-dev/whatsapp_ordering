import math
import logging
import time
from typing import List, Optional
from collections import Counter
from fastapi import APIRouter, HTTPException, Header, Depends, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from jose import JWTError, jwt
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import (
    Restaurant, Order, OrderItem, OrderItemExclusion, OrderItemModifier,
    MenuItem, Category, ModifierOption, ModifierGroup, OrderStatus, FulfillmentMethod, Customer,
    WalletTransaction, TransactionType
)
from app.services.socket_manager import manager
from app.services.whatsapp import WhatsAppService
from app.services.order_service import OrderService
from app.services.hours import is_restaurant_open
from app.services.event_engine import queue_event

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory rate limiter for the public beacon endpoint (mirrors webhook.py)
# ---------------------------------------------------------------------------
_BEACON_RATE_LIMIT: dict = {}          # ip -> last_request_timestamp
_BEACON_RATE_WINDOW_S: float = 2.0    # 30 req/min ≈ 1 per 2s per IP
_BEACON_MAX_ENTRIES: int = 20000

# Whitelisted event types the PWA is allowed to emit (server enforced)
_ALLOWED_PWA_EVENT_TYPES = frozenset({
    "menu.viewed",
    "product.added_to_cart",
    "checkout.started",
})

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
    modifiers: Optional[List[int]] = []

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
async def process_checkout(
    payload: CheckoutPayload,
    background_tasks: BackgroundTasks,
    session_payload: dict = Depends(verify_session_token),
):
    wa_id = session_payload.get("sub")
    restaurant_id = session_payload.get("rid")
    if not wa_id or not restaurant_id:
        raise HTTPException(status_code=401, detail="Invalid session claims")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart cannot be empty")

    async with AsyncSessionLocal() as db:
        # FIX-1: Atomic row-lock to prevent wallet race condition on concurrent checkouts
        res = await db.execute(
            select(Restaurant)
            .where(Restaurant.id == restaurant_id)
            .with_for_update()
        )
        restaurant = res.scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # Gate — reject checkout if store is closed (manual override OR outside operating hours)
        if not is_restaurant_open(restaurant):
            raise HTTPException(status_code=400, detail="This restaurant is currently closed and not accepting orders. Please try again later.")

        # 1. Geo-Fencing & Delivery Fee Calculation
        delivery_fee = 0.0
        if payload.fulfillment_method == "delivery":
            # FIX-5: Reject delivery orders with missing GPS instead of silently defaulting to Casablanca
            if not payload.latitude or not payload.longitude:
                raise HTTPException(status_code=400, detail="Location is required for delivery orders. Please enable GPS and try again.")

            if not restaurant.latitude or not restaurant.longitude:
                # Restaurant hasn't configured its own GPS — fallback to base fee only
                delivery_fee = round(float(restaurant.base_delivery_fee), 2)
                distance_km = 0.0
            else:
                distance_km = round(float(calculate_haversine_distance(
                    float(restaurant.latitude), float(restaurant.longitude),
                    float(payload.latitude), float(payload.longitude)
                )), 4)
                if distance_km > float(restaurant.max_delivery_radius_km):
                    raise HTTPException(status_code=400, detail=f"Location is outside our delivery radius (Max: {restaurant.max_delivery_radius_km} km)")

                base_fee = round(float(restaurant.base_delivery_fee), 2)
                per_km_fee = round(float(restaurant.per_km_delivery_fee), 2)
                delivery_fee = round(base_fee + (distance_km * per_km_fee), 2)

        # 2. Server-side Pricing
        method = FulfillmentMethod.DELIVERY if payload.fulfillment_method == "delivery" else FulfillmentMethod.PICKUP
        cart_total = 0.0

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

        for req_item in payload.items:
            if req_item.quantity < 1:
                raise HTTPException(status_code=400, detail="Item quantity must be at least 1")

            # Validate item ownership & price
            item_q = await db.execute(
                select(MenuItem)
                .join(Category)
                .where(MenuItem.id == req_item.menu_item_id, Category.restaurant_id == restaurant_id)
                .options(
                    selectinload(MenuItem.modifier_groups).selectinload(ModifierGroup.options)
                )
            )
            menu_item = item_q.scalar_one_or_none()
            if not menu_item or not menu_item.is_available:
                raise HTTPException(status_code=400, detail=f"Item {req_item.menu_item_id} is unavailable")

            order_line = OrderItem(
                order_id=new_order.id,
                menu_item_id=menu_item.id,
                quantity=req_item.quantity,
                unit_price=round(float(menu_item.price), 2)
            )
            db.add(order_line)
            await db.flush()

            # Line price starts at base item price
            line_price = round(float(menu_item.price), 2)
            modifier_total = 0.0

            # Exclusions
            for exc in req_item.exclusions:
                db.add(OrderItemExclusion(order_item_id=order_line.id, ingredient_name=exc))

            # Modifiers — with server-side constraint validation
            # FIX-2 & FIX-3: Validate modifier availability AND enforce min/max selection
            group_selection_counts = Counter()  # {group_id: count}

            valid_options = {}
            for grp in menu_item.modifier_groups:
                for opt in grp.options:
                    valid_options[opt.id] = (opt, grp.id)

            for mod_id in req_item.modifiers:
                if mod_id not in valid_options:
                    raise HTTPException(status_code=400, detail=f"Modifier option {mod_id} is invalid for this item")
                
                mod_opt, group_id = valid_options[mod_id]
                
                # FIX-3: Block unavailable modifier options
                if not mod_opt.is_available:
                    raise HTTPException(status_code=400, detail=f"Modifier option {mod_id} is unavailable")
                
                group_selection_counts[group_id] += 1
                db.add(OrderItemModifier(order_item_id=order_line.id, modifier_option_id=mod_id))
                modifier_total += round(float(mod_opt.price_override), 2)

            # FIX-2: Enforce modifier group min/max selection bounds
            # Also check mandatory groups that received zero selections
            item_groups = menu_item.modifier_groups
            for grp in item_groups:
                count = group_selection_counts.get(grp.id, 0)
                if count < grp.min_selection:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Modifier group '{grp.name_en}' requires at least {grp.min_selection} selection(s), got {count}"
                    )
                if count > grp.max_selection:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Modifier group '{grp.name_en}' allows at most {grp.max_selection} selection(s), got {count}"
                    )

            modifier_total = round(modifier_total, 2)
            line_price = round(line_price + modifier_total, 2)
            line_total = round(line_price * int(req_item.quantity), 2)
            order_line.unit_price = line_price
            cart_total = round(cart_total + line_total, 2)

        # 3. Finalize Totals & Delivery PIN
        final_total = round(cart_total + delivery_fee, 2)

        # X-RAY LOGGING: Inspect all pricing components before committing
        logger.info(
            f"MATH X-RAY | order_id_pending | "
            f"Cart: {cart_total} MAD | "
            f"Dist(km): {distance_km if payload.fulfillment_method == 'delivery' else 'N/A (pickup)'} | "
            f"Del Fee: {delivery_fee} MAD | "
            f"Final: {final_total} MAD"
        )

        new_order.total_price = final_total
        new_order.delivery_pin = await OrderService.generate_delivery_pin(db)
        
        # Enforce Grace Period — order-count based buffer (-25 unpaid orders)
        # Only evaluate when the wallet is already negative to avoid a DB round-trip on every order
        if restaurant.wallet_balance < 0.0:
            unpaid_count_res = await db.execute(
                select(func.count(Order.id)).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status.notin_([OrderStatus.CANCELLED, OrderStatus.DELIVERED]),
                )
            )
            unpaid_count = unpaid_count_res.scalar() or 0
            if unpaid_count >= 25:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Le restaurant a atteint sa limite de tolérance (25 commandes en attente "
                        "de régularisation). Veuillez recharger votre portefeuille."
                    ),
                )
            
        # Deduct from Prepaid Wallet (row already locked by .with_for_update() above)
        if restaurant.subscription_tier.value == "STARTER":
            toll_amount = -3.0
            restaurant.wallet_balance += toll_amount
            transaction = WalletTransaction(
                restaurant_id=restaurant_id,
                amount=toll_amount,
                type=TransactionType.DEBIT,
                description=f"Frais de service commande #GQ-{new_order.id}"
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

        # 5. Emit instrumentation events (non-blocking, runs after response)
        queue_event(
            background_tasks,
            event_type="order.placed",
            channel="pwa",
            restaurant_id=restaurant_id,
            phone_number=wa_id,
            payload={
                "order_id": new_order.id,
                "total_price": new_order.total_price,
                "delivery_fee": new_order.delivery_fee,
                "fulfillment_method": new_order.fulfillment_method.value,
                "item_count": len(payload.items),
            },
        )
        if restaurant.subscription_tier.value == "STARTER":
            queue_event(
                background_tasks,
                event_type="wallet.toll_charged",
                channel="system",
                restaurant_id=restaurant_id,
                payload={
                    "amount": -3.0,
                    "order_id": new_order.id,
                    "new_balance": round(restaurant.wallet_balance, 4),
                },
            )

        return {
            "success": True,
            "order_id": new_order.id,
            "total_price": new_order.total_price,
            "delivery_fee": new_order.delivery_fee
        }


# ---------------------------------------------------------------------------
# Public Client Beacon Endpoint
# ---------------------------------------------------------------------------

class BeaconPayload(BaseModel):
    event_id: Optional[str] = None
    event_type: str
    restaurant_id: int
    channel: str = "pwa"
    payload: Optional[dict] = None


@router.post("/events")
async def client_event_beacon(
    request: Request,
    body: BeaconPayload,
    background_tasks: BackgroundTasks,
):
    """
    Public client beacon endpoint for the Consumer Menu PWA.
    Accepts funnel events (menu.viewed, product.added_to_cart, checkout.started).
    Rate-limited per client IP. No authentication required.
    Events are written asynchronously — response is immediate.
    """
    # --- IP-based rate limiting (mirrors webhook.py pattern, no extra deps) ---
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    last_ts = _BEACON_RATE_LIMIT.get(client_ip, 0)
    if now - last_ts < _BEACON_RATE_WINDOW_S:
        raise HTTPException(status_code=429, detail="Too many events. Please slow down.")
    _BEACON_RATE_LIMIT[client_ip] = now
    if len(_BEACON_RATE_LIMIT) > _BEACON_MAX_ENTRIES:
        _BEACON_RATE_LIMIT.clear()

    # --- Whitelist enforcement ---
    if body.event_type not in _ALLOWED_PWA_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Event type '{body.event_type}' is not allowed on this endpoint.",
        )

    # --- Enqueue (non-blocking, response returns immediately) ---
    queue_event(
        background_tasks,
        event_type=body.event_type,
        channel="pwa",
        restaurant_id=body.restaurant_id,
        payload=body.payload or {},
        event_id=body.event_id,
    )

    return {"accepted": True}
