import random
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from jose import JWTError, jwt
from app.core.database import AsyncSessionLocal
from app.core.auth import (
    SECRET_KEY, ALGORITHM, get_current_cashier_or_above, get_current_kitchen_or_above,
    get_current_user, assert_restaurant_access
)
from app.models import Order, OrderStatus, OrderItem, MenuItem, Customer, User, UserRole, Category, FulfillmentMethod, Driver, Restaurant, OrderItemModifier, SubscriptionTier

from app.services.order_service import OrderService
from app.services.socket_manager import manager
from app.services.event_engine import queue_event

router = APIRouter()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class MenuItemCompactSchema(BaseModel):
    name_en: str
    name_fr: str
    name_ar: str

    class Config:
        from_attributes = True

class ModifierOptionCompactSchema(BaseModel):
    id: int
    name_en: str
    name_fr: str
    name_ar: str

    class Config:
        from_attributes = True

class OrderItemModifierSchema(BaseModel):
    id: int
    modifier_option_id: int
    modifier_option: Optional[ModifierOptionCompactSchema] = None

    class Config:
        from_attributes = True

class OrderItemExclusionSchema(BaseModel):
    id: int
    ingredient_name: str

    class Config:
        from_attributes = True

class OrderItemSchema(BaseModel):
    id: int
    menu_item_id: int
    quantity: int
    unit_price: float
    name_en: Optional[str] = None
    name_fr: Optional[str] = None
    name_ar: Optional[str] = None
    menu_item: Optional[MenuItemCompactSchema] = None
    exclusions: List[OrderItemExclusionSchema] = []
    modifiers: List[OrderItemModifierSchema] = []

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


class DriverSchema(BaseModel):
    id: int
    name: str
    phone_number: Optional[str] = None

    class Config:
        from_attributes = True


class CustomerSchema(BaseModel):
    id: int
    whatsapp_id: str
    name: str
    phone_number: Optional[str] = None

    class Config:
        from_attributes = True
class OrderSchema(BaseModel):
    id: int
    tracking_code: str = Field(..., description="Unique alphanumeric tracking code.", example="GQ-1042")
    restaurant_id: int
    customer_wa_id: str
    fulfillment_method: str
    status: str = Field(..., description="Order status.", example="PREPARING")
    total_price: float
    delivery_fee: Optional[float] = Field(0.0, description="Delivery fee in MAD.", example=15.0)
    delivery_pin: Optional[str] = Field(None, description="4-digit driver PIN for delivery verification.", example="5921")
    customer_notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    items: List[OrderItemSchema] = []
    driver: Optional[DriverSchema] = None
    customer: Optional[CustomerSchema] = None

    class Config:
        from_attributes = True


class StatusUpdateBody(BaseModel):
    new_status: OrderStatus = Field(..., description="The new order status (e.g. PREPARING, READY_FOR_DELIVERY, DELIVERED, CANCELLED).", example="PREPARING")
    driver_id: Optional[int] = None

class DeliverySettingsUpdate(BaseModel):
    latitude: float
    longitude: float
    max_delivery_radius_km: float
    base_delivery_fee: float
    per_km_delivery_fee: Optional[float] = 0.0
    operating_hours: Optional[str] = None
    city: Optional[str] = None

class RestaurantStatusUpdate(BaseModel):
    is_accepting_orders: bool = Field(..., description="Whether the restaurant is currently accepting new orders.", example=True)


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
    token: Optional[str] = None
    selected_subprotocol: Optional[str] = None

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
    """Returns all orders (daily ledger). Terminal orders are kept for 24 hours."""
    from datetime import datetime, timedelta
    
    assert_restaurant_access(current_user, restaurant_id)
    async with AsyncSessionLocal() as db:
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        query = await db.execute(
            select(Order)
            .where(Order.restaurant_id == restaurant_id)
            .where(
                or_(
                    ~Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CANCELLED]),
                    and_(
                        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CANCELLED]),
                        Order.created_at >= twenty_four_hours_ago
                    )
                )
            )
            .options(
                joinedload(Order.items).joinedload(OrderItem.menu_item),
                joinedload(Order.items).joinedload(OrderItem.modifiers).joinedload(OrderItemModifier.modifier_option),
                joinedload(Order.items).joinedload(OrderItem.exclusions)
            )
            .order_by(Order.created_at.desc())
        )
        orders = query.scalars().unique().all()
        return orders


@router.get("/deliveries/{restaurant_id}", response_model=List[OrderSchema])
async def get_deliveries(
    restaurant_id: int,
    current_user: User = Depends(get_current_kitchen_or_above)
):
    """Returns dispatched and recently delivered orders for the logistics board."""
    from datetime import datetime, timedelta
    
    assert_restaurant_access(current_user, restaurant_id)
    async with AsyncSessionLocal() as db:
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        
        query = await db.execute(
            select(Order)
            .where(Order.restaurant_id == restaurant_id)
            .where(
                and_(
                    Order.status.in_([OrderStatus.DISPATCHED, OrderStatus.DELIVERED]),
                    Order.created_at >= twenty_four_hours_ago
                )
            )
            .options(
                joinedload(Order.items).joinedload(OrderItem.menu_item),
                joinedload(Order.items).joinedload(OrderItem.modifiers).joinedload(OrderItemModifier.modifier_option),
                joinedload(Order.items).joinedload(OrderItem.exclusions),
                joinedload(Order.driver)
            )
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

        # ── Handle driver dispatch logic ──
        if body.new_status == OrderStatus.DISPATCHED:
            # Step 1: Require a driver for dispatch
            if not body.driver_id:
                raise HTTPException(status_code=400, detail="A driver must be assigned before dispatching.")

            driver_res = await db.execute(select(Driver).where(Driver.id == body.driver_id))
            driver = driver_res.scalar_one_or_none()
            if not driver or driver.restaurant_id != order.restaurant_id:
                raise HTTPException(status_code=400, detail="Invalid driver")
            order.driver_id = body.driver_id

            # Step 2: Generate strict 6-digit numeric PIN
            order.delivery_pin = "".join(random.choices(string.digits, k=6))

            # Step 3: Re-fetch customer (already fetched above but ensure we have full object)
            if not customer:
                raise HTTPException(status_code=400, detail="Customer record not found for this order.")

            restaurant = order.restaurant
            if restaurant and restaurant.api_token and restaurant.phone_number_id:
                # Step 4: Trilingual customer message with PIN
                pin_msg = {
                    "fr": (
                        f"🛵 Bonne nouvelle ! Le livreur *{driver.name}* est en route !\n"
                        f"Pour recevoir votre commande, donnez ce code PIN au livreur : *{order.delivery_pin}*"
                    ),
                    "ar": (
                        f"🛵 خبر سار! السائق *{driver.name}* في الطريق إليك!\n"
                        f"لاستلام طلبك، أعطِ السائق رمز PIN هذا: *{order.delivery_pin}*"
                    ),
                    "en": (
                        f"🛵 Good news! Driver *{driver.name}* is on the way!\n"
                        f"To receive your order, please give the driver this secure PIN: *{order.delivery_pin}*"
                    ),
                }.get(customer_lang, "fr")

                background_tasks.add_task(
                    _dispatch_notifications_background,
                    restaurant_token=restaurant.api_token,
                    restaurant_phone_id=restaurant.phone_number_id,
                    customer_wa_id=order.customer_wa_id,
                    customer_pin_msg=pin_msg,
                    driver_wa_id=driver.wa_id,
                    order_id=order.id,
                    order_tracking_code=order.tracking_code,
                    order_total_price=order.total_price,
                    order_latitude=order.latitude,
                    order_longitude=order.longitude,
                    customer_wa_id_for_driver=order.customer_wa_id,
                )

        # ── No PIN is generated on ACCEPTED. PIN is generated exclusively on DISPATCHED. ──

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

        # Emit KDS lifecycle instrumentation events (non-blocking)
        _kds_event_map = {
            OrderStatus.ACCEPTED.value: "order.kds_sent",
            OrderStatus.READY.value: "order.kds_ready",
            OrderStatus.DISPATCHED.value: "order.dispatched",
        }
        kds_event_type = _kds_event_map.get(new_status_val)
        if kds_event_type:
            queue_event(
                background_tasks,
                event_type=kds_event_type,
                channel="kds",
                restaurant_id=order.restaurant_id,
                payload={"order_id": order.id, "new_status": new_status_val},
            )

        # Trigger generic status WhatsApp notification (skipped for DISPATCHED — handled above with PIN)
        if body.new_status != OrderStatus.DISPATCHED:
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


async def _dispatch_notifications_background(
    restaurant_token: str,
    restaurant_phone_id: str,
    customer_wa_id: str,
    customer_pin_msg: str,
    driver_wa_id: str,
    order_id: int,
    order_tracking_code: str,
    order_total_price: float,
    order_latitude: Optional[float],
    order_longitude: Optional[float],
    customer_wa_id_for_driver: str,
):
    """
    Runs in the background after a DISPATCHED status update.
    Sends:
      1. A plain-text PIN message to the customer.
      2. A WhatsApp Flow dispatch card to the driver.
    """
    import logging
    logger = logging.getLogger(__name__)

    from app.services.whatsapp import WhatsAppService

    wa = WhatsAppService(token=restaurant_token, phone_id=restaurant_phone_id)

    # --- 1. Customer PIN message ---
    try:
        await wa.send_text_message(customer_wa_id, customer_pin_msg)
    except Exception as e:
        logger.error("[Dispatch] Failed to send customer PIN message: %s", e)

    # --- 2. Driver dispatch Flow ---
    # Build a lightweight data container for the service call
    class _OrderStub:
        def __init__(self):
            self.id = order_id
            self.tracking_code = order_tracking_code
            self.total_price = order_total_price
            self.latitude = order_latitude
            self.longitude = order_longitude

    class _CustomerStub:
        def __init__(self):
            self.wa_id = customer_wa_id_for_driver

    try:
        await wa.send_driver_dispatch_message(
            to_phone=driver_wa_id,
            order=_OrderStub(),
            customer=_CustomerStub(),
        )
    except Exception as e:
        logger.error("[Dispatch] Failed to send driver dispatch Flow: %s", e)


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
        if payload.operating_hours is not None:
            restaurant.operating_hours = payload.operating_hours
        if payload.city is not None:
            restaurant.city = payload.city
        
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


# ---------------------------------------------------------------------------
# Daily Driver Delivery Summary
# GET /api/v1/dashboard/deliveries/daily-summary/{restaurant_id}
# ---------------------------------------------------------------------------

@router.get("/deliveries/daily-summary/{restaurant_id}")
async def get_daily_driver_summary(
    restaurant_id: int,
    current_user: User = Depends(get_current_user),
):
    """
    Returns today's completed delivery orders aggregated by driver.
    Time window: 00:00:00 → now in Casablanca local time (UTC+1, no DST).
    Auth: user must belong to the restaurant or be ADMIN.
    """
    # -- Access control --
    if current_user.role != UserRole.ADMIN and current_user.restaurant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="You do not have access to this restaurant")

    # -- Today's window in Casablanca time (UTC+1, Morocco Standard Time) --
    casablanca_offset = timezone(timedelta(hours=1))
    now_local = datetime.now(casablanca_offset)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Convert back to UTC for DB comparison (DB stores UTC naive datetimes)
    today_start_utc = today_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    now_utc = now_local.astimezone(timezone.utc).replace(tzinfo=None)

    async with AsyncSessionLocal() as db:
        # Fetch all DELIVERED delivery orders for this restaurant today
        result = await db.execute(
            select(Order)
            .where(
                and_(
                    Order.restaurant_id == restaurant_id,
                    Order.status == OrderStatus.DELIVERED,
                    Order.fulfillment_method == FulfillmentMethod.DELIVERY,
                    Order.created_at >= today_start_utc,
                    Order.created_at <= now_utc,
                )
            )
            .options(joinedload(Order.driver))
            .order_by(Order.created_at.asc())
        )
        orders = result.scalars().unique().all()

        # Fetch all drivers for this restaurant to ensure we include zero-delivery agents
        drivers_result = await db.execute(
            select(Driver).where(Driver.restaurant_id == restaurant_id)
        )
        all_drivers = drivers_result.scalars().all()

    # -- Aggregate by driver --
    # driver_id → {"driver": Driver, "orders": [Order, ...]}
    driver_buckets: Dict[Optional[int], Dict[str, Any]] = {}

    # Pre-populate with all known drivers so zero-delivery agents appear
    for d in all_drivers:
        driver_buckets[d.id] = {"driver": d, "orders": []}

    # Unassigned bucket for orders with no driver set
    for order in orders:
        key = order.driver_id  # may be None
        if key not in driver_buckets:
            driver_buckets[key] = {"driver": order.driver, "orders": []}
        driver_buckets[key]["orders"].append(order)

    # -- Build response payload --
    total_deliveries = len(orders)
    total_cash = sum(o.total_price for o in orders)

    drivers_payload = []
    for driver_id, bucket in driver_buckets.items():
        driver_obj = bucket["driver"]
        bucket_orders = bucket["orders"]
        cash = sum(o.total_price for o in bucket_orders)

        driver_name = driver_obj.name if driver_obj else "Unassigned"
        driver_wa  = driver_obj.wa_id if driver_obj else None
        driver_active = driver_obj.is_active if driver_obj else False

        drivers_payload.append({
            "driver_id":       driver_id,
            "driver_name":     driver_name,
            "driver_phone":    driver_wa,   # wa_id used as phone identifier
            "is_active":       driver_active,
            "deliveries_count": len(bucket_orders),
            "cash_collected":  round(cash, 2),
            "orders": [
                {
                    "id":             o.id,
                    "tracking_code":  o.tracking_code,
                    "customer_name":  o.customer_name or o.customer_wa_id,
                    "total_amount":   o.total_price,
                    "delivered_at":   o.created_at.isoformat() + "Z",
                }
                for o in bucket_orders
            ],
        })

    # Sort: drivers with deliveries first, then alphabetically
    drivers_payload.sort(key=lambda d: (-d["deliveries_count"], d["driver_name"] or ""))

    return {
        "date": now_local.strftime("%Y-%m-%d"),
        "total_deliveries_today": total_deliveries,
        "total_cash_collected_today": round(total_cash, 2),
        "drivers": drivers_payload,
    }


# ---------------------------------------------------------------------------
# Owner Latest Monthly PDF — Manifest endpoint
# GET /api/v1/dashboard/reports/my-latest-pdf
# ---------------------------------------------------------------------------

@router.get("/reports/my-latest-pdf")
async def get_my_latest_pdf_manifest(
    current_user: User = Depends(get_current_user),
):
    """
    Returns report availability manifest for the previous calendar month.
    Tier-gated: SCALE and MULTI only.
    If the restaurant was created in the current calendar month (first month of
    operation), returns has_report=false with a first-month notice message.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned to your account")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Restaurant).where(Restaurant.id == current_user.restaurant_id)
        )
        restaurant = result.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # -- Tier gate --
    if restaurant.subscription_tier not in (SubscriptionTier.SCALE, SubscriptionTier.MULTI):
        raise HTTPException(
            status_code=403,
            detail="Les rapports PDF mensuels sont disponibles à partir du forfait Scale."
        )

    # -- Determine previous calendar month --
    now = datetime.utcnow()
    if now.month == 1:
        report_month = 12
        report_year  = now.year - 1
    else:
        report_month = now.month - 1
        report_year  = now.year

    # -- First-month check --
    created = restaurant.created_at  # UTC naive datetime
    created_month = (created.year, created.month)
    current_month  = (now.year, now.month)

    if created_month == current_month:
        # Restaurant created this calendar month — no completed month yet
        return JSONResponse(content={
            "has_report": False,
            "report_month": report_month,
            "report_year":  report_year,
            "restaurant_name": restaurant.name,
            "message": (
                "Votre premier rapport d'analyse mensuel sera disponible "
                "à la fin de votre premier mois d'activité."
            ),
        })

    # -- Report available: return manifest (actual PDF bytes generated on demand via batch-dispatch) --
    return {
        "has_report":      True,
        "report_month":    report_month,
        "report_year":     report_year,
        "restaurant_id":   restaurant.id,
        "restaurant_name": restaurant.name,
        "pdf_url": (
            f"/api/v1/admin/reports/preview/{restaurant.id}"
            f"?month={report_month}&year={report_year}"
        ),
    }