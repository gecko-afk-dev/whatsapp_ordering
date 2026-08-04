from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body, BackgroundTasks, Query, Depends
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from jose import JWTError, jwt
from app.core.database import AsyncSessionLocal
from app.core.auth import (
    SECRET_KEY, ALGORITHM, get_current_cashier_or_above, get_current_kitchen_or_above,
    assert_restaurant_access
)
from app.models import Order, OrderStatus, OrderItem, MenuItem, Customer, User, UserRole, Category, FulfillmentMethod, Driver, Restaurant

from app.services.order_service import OrderService
from app.services.socket_manager import manager

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class OrderItemSchema(BaseModel):
    id: int
    menu_item_id: int
    quantity: int
    unit_price: float
    name_en: Optional[str] = None
    name_fr: Optional[str] = None
    name_ar: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def model_validate(cls, obj, **kwargs):
        data = super().model_validate(obj, **kwargs)
        if hasattr(obj, 'menu_item') and obj.menu_item:
            data.name_en = obj.menu_item.name_en
            data.name_fr = obj.menu_item.name_fr
            data.name_ar = obj.menu_item.name_ar
        return data

    @classmethod
    def from_orm(cls, obj):
        data = super().from_orm(obj)
        if hasattr(obj, 'menu_item') and obj.menu_item:
            data.name_en = obj.menu_item.name_en
            data.name_fr = obj.menu_item.name_fr
            data.name_ar = obj.menu_item.name_ar
        return data


class OrderSchema(BaseModel):
    id: int
    tracking_code: str
    restaurant_id: int
    customer_wa_id: str
    fulfillment_method: str
    status: str
    total_price: float
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime
    items: List[OrderItemSchema] = []

    class Config:
        from_attributes = True


class StatusUpdateBody(BaseModel):
    new_status: OrderStatus
    driver_id: Optional[int] = None

class DeliverySettingsUpdate(BaseModel):
    latitude: float
    longitude: float
    max_delivery_radius_km: float
    base_delivery_fee: float
    per_km_delivery_fee: float

class RestaurantStatusUpdate(BaseModel):
    is_accepting_orders: bool


# ---------------------------------------------------------------------------
# WebSocket auth helper
# ---------------------------------------------------------------------------

async def get_user_from_token(token: str) -> Optional[User]:
    """Decode a JWT and return the matching User, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.websocket("/ws/{restaurant_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    restaurant_id: int,
):
    """
    Live KDS feed for the dashboard.

    Auth priority:
      1. httpOnly cookie `access_token`  — used in production (same-origin or
         cross-site with SameSite=lax + CORS credentials).
      2. Sec-WebSocket-Protocol: bearer.{token}  — dev fallback or legacy clients.
    Both paths validate the same JWT with the same secret.
    """
    token: str | None = None
    selected_subprotocol: str | None = None

    # 1. Try cookie auth first (preferred — no token in JS memory)
    cookie_token = websocket.cookies.get("access_token")
    if cookie_token:
        token = cookie_token

    # 2. Fall back to subprotocol (dev cross-origin or legacy clients)
    if not token:
        protocol_header = websocket.headers.get("sec-websocket-protocol", "")
        protocols = [p.strip() for p in protocol_header.split(",") if p.strip()]
        bearer_proto = next(
            (p for p in protocols if p.startswith("bearer.")), None
        )
        if bearer_proto:
            token = bearer_proto[len("bearer."):]
            selected_subprotocol = bearer_proto

    # 3. Reject if no credential found
    if not token:
        await websocket.close(code=4001)
        return

    # 4. Validate token and load user
    user = await get_user_from_token(token)
    if not user or not user.is_active:
        await websocket.close(code=4001)
        return

    # Accept — echo subprotocol only when the client sent one (RFC 6455)
    await websocket.accept(subprotocol=selected_subprotocol)

    # 5. Restaurant-scoped access control
    if user.role != UserRole.ADMIN:
        if user.restaurant_id != restaurant_id:
            await websocket.close(code=4003)
            return

    await manager.connect(websocket, restaurant_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, restaurant_id)


@router.get("/orders/{restaurant_id}", response_model=List[OrderSchema])
async def get_active_orders(
    restaurant_id: int,
    current_user: User = Depends(get_current_kitchen_or_above)
):
    """Returns all non-terminal orders for a restaurant."""
    assert_restaurant_access(current_user, restaurant_id)
    async with AsyncSessionLocal() as db:
        query = await db.execute(
            select(Order)
            .where(Order.restaurant_id == restaurant_id)
            .where(
                Order.status.in_(
                    [
                        OrderStatus.RECEIVED,
                        OrderStatus.ACCEPTED,
                        OrderStatus.PREPARING,
                        OrderStatus.READY,
                    ]
                )
            )
            .options(joinedload(Order.items).joinedload(OrderItem.menu_item))
            .order_by(Order.created_at.desc())
        )
        orders = query.scalars().unique().all()
        return orders


@router.post("/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    background_tasks: BackgroundTasks,
    body: StatusUpdateBody = Body(...),
    current_user: User = Depends(get_current_cashier_or_above)
):
    """Called when the cashier clicks Accept, Preparing, etc."""
    async with AsyncSessionLocal() as db:
        query = select(Order).options(joinedload(Order.restaurant)).where(Order.id == order_id)
        res = await db.execute(query)
        order = res.scalar_one_or_none()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Verify restaurant access
        assert_restaurant_access(current_user, order.restaurant_id)

        # Fetch the customer's language preference
        cust_query = select(Customer).where(Customer.wa_id == order.customer_wa_id)
        cust_res = await db.execute(cust_query)
        customer = cust_res.scalar_one_or_none()
        customer_lang = customer.language if customer and customer.language else "fr"

        # Write audit log
        from app.services.audit import log_audit_action
        await log_audit_action(
            db=db,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            action="ORDER_STATUS_UPDATED",
            target=f"order_id={order.id}",
            detail={"old": order.status.value, "new": body.new_status.value},
            restaurant_id=order.restaurant_id
        )

        # Generate delivery PIN if accepting a delivery order
        if body.new_status == OrderStatus.ACCEPTED and order.fulfillment_method == FulfillmentMethod.DELIVERY and not order.delivery_pin:
            order.delivery_pin = await OrderService.generate_delivery_pin(db)

        # Handle driver dispatch logic
        if body.new_status == OrderStatus.DISPATCHED:
            restaurant = order.restaurant
            if body.driver_id:
                # Direct Assignment
                driver_res = await db.execute(select(Driver).where(Driver.id == body.driver_id))
                driver = driver_res.scalar_one_or_none()
                if not driver or driver.restaurant_id != order.restaurant_id:
                    raise HTTPException(status_code=400, detail="Invalid driver")
                order.driver_id = body.driver_id
                
                if restaurant and restaurant.api_token and restaurant.phone_number_id:
                    background_tasks.add_task(
                        OrderService.notify_driver_dispatch_background,
                        restaurant_token=restaurant.api_token,
                        restaurant_phone_id=restaurant.phone_number_id,
                        driver_wa_id=driver.wa_id,
                        order_id=order.id,
                        latitude=order.latitude or 0.0,
                        longitude=order.longitude or 0.0
                    )
            else:
                # Broadcast
                order.driver_id = None
                if restaurant and restaurant.api_token and restaurant.phone_number_id:
                    background_tasks.add_task(
                        OrderService.notify_drivers_broadcast_background,
                        db=None,
                        restaurant_token=restaurant.api_token,
                        restaurant_phone_id=restaurant.phone_number_id,
                        restaurant_id=restaurant.id,
                        order_id=order.id
                    )
        
        # Update order status
        order.status = body.new_status
        await db.commit()

        # Broadcast update to the frontend dashboard
        new_status_val = body.new_status.value
        await manager.broadcast_to_restaurant(
            order.restaurant_id,
            {
                "event": "ORDER_STATUS_UPDATED",
                "order_id": order.id,
                "new_status": new_status_val,
            },
        )

        # Trigger WhatsApp notification in the background
        restaurant = order.restaurant
        if restaurant and restaurant.api_token and restaurant.phone_number_id:
            background_tasks.add_task(
                OrderService.notify_customer_background,
                restaurant_token=restaurant.api_token,
                restaurant_phone_id=restaurant.phone_number_id,
                customer_wa_id=order.customer_wa_id,
                customer_lang=customer_lang,
                order_id=order.id,
                status=new_status_val,
                delivery_pin=order.delivery_pin
            )

        return {"status": "updated", "new_status": new_status_val}


@router.post("/items/{item_id}/toggle-availability")
async def toggle_item_availability(
    item_id: int,
    current_user: User = Depends(get_current_cashier_or_above),
):
    """Toggle item availability. Allowed for restaurant owner and cashiers."""
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned to your account")

    async with AsyncSessionLocal() as db:
        # Verify the item belongs to the caller's restaurant before toggling
        res = await db.execute(
            select(MenuItem)
            .join(Category, MenuItem.category_id == Category.id)
            .where(
                and_(
                    MenuItem.id == item_id,
                    Category.restaurant_id == current_user.restaurant_id
                )
            )
        )
        item = res.scalar_one_or_none()

        if not item:
            raise HTTPException(
                status_code=404,
                detail="Item not found or does not belong to your restaurant"
            )

        item.is_available = not item.is_available
        await db.commit()

        # Write audit log
        from app.services.audit import log_audit_action
        await log_audit_action(
            db=db,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            action="ITEM_AVAILABILITY_TOGGLED",
            target=f"item_id={item.id}",
            detail={"item_name": item.name_en, "is_available": item.is_available},
            restaurant_id=current_user.restaurant_id
        )

        return {"status": "toggled", "is_available": item.is_available}

@router.put("/restaurant/delivery-settings")
async def update_delivery_settings(
    payload: DeliverySettingsUpdate,
    current_user: User = Depends(get_current_kitchen_or_above)
):
    """Update geo-fencing and delivery settings. Requires Owner or Admin."""
    if current_user.role not in [UserRole.RESTAURANT_OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned")
        
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Restaurant).where(Restaurant.id == current_user.restaurant_id))
        restaurant = res.scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")
            
        restaurant.latitude = payload.latitude
        restaurant.longitude = payload.longitude
        restaurant.max_delivery_radius_km = payload.max_delivery_radius_km
        restaurant.base_delivery_fee = payload.base_delivery_fee
        restaurant.per_km_delivery_fee = payload.per_km_delivery_fee
        
        await db.commit()
        return {"status": "success"}

@router.put("/restaurant/status")
async def update_restaurant_status(
    payload: RestaurantStatusUpdate,
    current_user: User = Depends(get_current_kitchen_or_above)
):
    """Toggle if restaurant is accepting orders. Requires Owner or Admin."""
    if current_user.role not in [UserRole.RESTAURANT_OWNER, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned")
        
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Restaurant).where(Restaurant.id == current_user.restaurant_id))
        restaurant = res.scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")
            
        restaurant.is_accepting_orders = payload.is_accepting_orders
        
        await db.commit()
        return {"status": "success", "is_accepting_orders": restaurant.is_accepting_orders}