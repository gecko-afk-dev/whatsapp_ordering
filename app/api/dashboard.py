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
    SECRET_KEY, ALGORITHM, get_current_restaurant_owner,
    get_current_cashier_or_above, get_current_kitchen_or_above,
    assert_restaurant_access
)
from app.models import Order, OrderStatus, OrderItem, MenuItem, Restaurant, Customer, User, UserRole, Category

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
    token: str = Query(default=None),
):
    """Live connection for the dashboard. Requires a valid JWT token."""
    # Reject connection immediately if no token provided
    if not token:
        await websocket.close(code=4001)
        return

    # Validate the token and load the user
    user = await get_user_from_token(token)
    if not user or not user.is_active:
        await websocket.close(code=4001)
        return

    # Restaurant-scoped roles can only connect to their own restaurant's feed
    if user.role != UserRole.ADMIN:
        if user.restaurant_id != restaurant_id:
            await websocket.close(code=4003)
            return

    # Admins can connect to any restaurant feed
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
        from app.api.admin import write_audit_log
        await write_audit_log(
            db=db,
            user=current_user,
            action="ORDER_STATUS_UPDATED",
            target=f"order_id={order.id}",
            detail=f"Order status changed to {body.new_status.value} (previously: {order.status.value})"
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
                status=new_status_val
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
        from app.api.admin import write_audit_log
        await write_audit_log(
            db=db,
            user=current_user,
            action="ITEM_AVAILABILITY_TOGGLED",
            target=f"item_id={item.id}",
            detail=f"Item '{item.name_en}' availability toggled to {'available' if item.is_available else 'unavailable'}"
        )

        return {"status": "toggled", "is_available": item.is_available}