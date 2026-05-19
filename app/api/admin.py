from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.future import select
from sqlalchemy import func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr
import json

from app.core.database import AsyncSessionLocal
from app.core.auth import get_current_admin, get_current_restaurant_owner, User, get_password_hash, verify_password, create_access_token
from app.services.email import EmailService
import secrets
from app.models import (
    Restaurant, RestaurantStatus, PaymentStatus, Order, OrderStatus,
    DailyAnalytics, User as UserModel, UserRole, MenuItem
)

router = APIRouter()

# --- Pydantic Schemas ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class RestaurantCreate(BaseModel):
    name: str
    wa_phone_number: str
    api_token: str
    phone_number_id: str
    owner_wa_id: str
    address: Optional[str] = None
    cuisine_type: Optional[str] = None
    contact_email: EmailStr
    commission_rate: float = 0.20

class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    wa_phone_number: Optional[str] = None
    api_token: Optional[str] = None
    phone_number_id: Optional[str] = None
    owner_wa_id: Optional[str] = None
    address: Optional[str] = None
    cuisine_type: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    commission_rate: Optional[float] = None
    status: Optional[RestaurantStatus] = None
    payment_status: Optional[PaymentStatus] = None

class AnalyticsSummary(BaseModel):
    total_restaurants: int
    active_restaurants: int
    total_orders_today: int
    total_revenue_today: float
    total_orders_month: int
    total_revenue_month: float
    avg_order_value: float

class RestaurantAnalytics(BaseModel):
    restaurant_id: int
    restaurant_name: str
    orders_today: int
    revenue_today: float
    orders_month: int
    revenue_month: float
    avg_order_value: float
    status: str
    payment_status: str

# --- Authentication ---

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Login for admins and restaurant owners."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserModel).where(UserModel.email == request.email)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Verify password against stored hash
        if not verify_password(request.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        access_token = create_access_token(data={"sub": user.email})

        return TokenResponse(
            access_token=access_token,
            user={
                "id": user.id,
                "email": user.email,
                "role": user.role.value,
                "restaurant_id": user.restaurant_id,
                "requires_password_change": user.requires_password_change
            }
        )

# --- Admin Routes ---

@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(current_user: User = Depends(get_current_admin)):
    """Get overall business analytics."""
    async with AsyncSessionLocal() as db:
        today = datetime.utcnow().date()
        month_start = today.replace(day=1)

        # Total restaurants
        total_restaurants_result = await db.execute(
            select(func.count(Restaurant.id))
        )
        total_restaurants = total_restaurants_result.scalar()

        # Active restaurants
        active_restaurants_result = await db.execute(
            select(func.count(Restaurant.id)).where(Restaurant.status == RestaurantStatus.ACTIVE)
        )
        active_restaurants = active_restaurants_result.scalar()

        # Today's orders and revenue
        today_orders_result = await db.execute(
            select(func.count(Order.id), func.sum(Order.total_price)).where(
                and_(func.date(Order.created_at) == today, Order.status != OrderStatus.CANCELLED)
            )
        )
        today_orders, today_revenue = today_orders_result.first()
        today_orders = today_orders or 0
        today_revenue = today_revenue or 0.0

        # Month's orders and revenue
        month_orders_result = await db.execute(
            select(func.count(Order.id), func.sum(Order.total_price)).where(
                and_(Order.created_at >= month_start, Order.status != OrderStatus.CANCELLED)
            )
        )
        month_orders, month_revenue = month_orders_result.first()
        month_orders = month_orders or 0
        month_revenue = month_revenue or 0.0

        # Average order value
        avg_order_value = month_revenue / month_orders if month_orders > 0 else 0.0

        return AnalyticsSummary(
            total_restaurants=total_restaurants,
            active_restaurants=active_restaurants,
            total_orders_today=today_orders,
            total_revenue_today=today_revenue,
            total_orders_month=month_orders,
            total_revenue_month=month_revenue,
            avg_order_value=avg_order_value
        )

@router.get("/analytics/restaurants", response_model=List[RestaurantAnalytics])
async def get_restaurant_analytics(current_user: User = Depends(get_current_admin)):
    """Get analytics for each restaurant."""
    async with AsyncSessionLocal() as db:
        today = datetime.utcnow().date()
        month_start = today.replace(day=1)

        # Get all restaurants with their metrics
        restaurants_result = await db.execute(
            select(Restaurant).options()
        )
        restaurants = restaurants_result.scalars().all()

        analytics = []
        for restaurant in restaurants:
            # Today's metrics
            today_result = await db.execute(
                select(func.count(Order.id), func.sum(Order.total_price)).where(
                    and_(
                        Order.restaurant_id == restaurant.id,
                        func.date(Order.created_at) == today,
                        Order.status != OrderStatus.CANCELLED
                    )
                )
            )
            today_orders, today_revenue = today_result.first()
            today_orders = today_orders or 0
            today_revenue = today_revenue or 0.0

            # Month's metrics
            month_result = await db.execute(
                select(func.count(Order.id), func.sum(Order.total_price)).where(
                    and_(
                        Order.restaurant_id == restaurant.id,
                        Order.created_at >= month_start,
                        Order.status != OrderStatus.CANCELLED
                    )
                )
            )
            month_orders, month_revenue = month_result.first()
            month_orders = month_orders or 0
            month_revenue = month_revenue or 0.0

            avg_order_value = month_revenue / month_orders if month_orders > 0 else 0.0

            analytics.append(RestaurantAnalytics(
                restaurant_id=restaurant.id,
                restaurant_name=restaurant.name,
                orders_today=today_orders,
                revenue_today=today_revenue,
                orders_month=month_orders,
                revenue_month=month_revenue,
                avg_order_value=avg_order_value,
                status=restaurant.status.value,
                payment_status=restaurant.payment_status.value
            ))

        return analytics

@router.post("/restaurants", response_model=dict)
async def create_restaurant(
    restaurant: RestaurantCreate,
    current_user: User = Depends(get_current_admin)
):
    """Create a new restaurant."""
    async with AsyncSessionLocal() as db:
        # Check if phone number already exists
        existing = await db.execute(
            select(Restaurant).where(Restaurant.wa_phone_number == restaurant.wa_phone_number)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered"
            )

        new_restaurant = Restaurant(
            name=restaurant.name,
            wa_phone_number=restaurant.wa_phone_number,
            api_token=restaurant.api_token,
            phone_number_id=restaurant.phone_number_id,
            owner_wa_id=restaurant.owner_wa_id,
            address=restaurant.address,
            cuisine_type=restaurant.cuisine_type,
            contact_email=restaurant.contact_email,
            commission_rate=restaurant.commission_rate
        )

        db.add(new_restaurant)
        await db.commit()
        await db.refresh(new_restaurant)

        # Create the restaurant owner account
        setup_token = secrets.token_urlsafe(32)
        # Using a dummy password hash that can't be logged into normally without the reset/setup flow
        new_user = UserModel(
            email=restaurant.contact_email,
            password_hash=get_password_hash(secrets.token_hex(16)),
            role=UserRole.RESTAURANT_OWNER,
            restaurant_id=new_restaurant.id,
            reset_token=setup_token,
            reset_token_expiry=datetime.utcnow() + timedelta(days=7),
            requires_password_change=True
        )
        db.add(new_user)
        await db.commit()

        # Dispatch the setup email
        from app.services.email import EmailService
        await EmailService.send_invite_email(restaurant.contact_email, setup_token)

        return {"message": "Restaurant and Manager account created. Invite email sent.", "restaurant_id": new_restaurant.id}

@router.get("/restaurants", response_model=List[dict])
async def list_restaurants(current_user: User = Depends(get_current_admin)):
    """List all restaurants."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Restaurant))
        restaurants = result.scalars().all()

        return [{
            "id": r.id,
            "name": r.name,
            "status": r.status.value,
            "payment_status": r.payment_status.value,
            "commission_rate": r.commission_rate,
            "contact_email": r.contact_email,
            "created_at": r.created_at.isoformat() if r.created_at else None
        } for r in restaurants]

@router.put("/restaurants/{restaurant_id}")
async def update_restaurant(
    restaurant_id: int,
    updates: RestaurantUpdate,
    current_user: User = Depends(get_current_admin)
):
    """Update restaurant details."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = result.scalar_one_or_none()

        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        update_data = updates.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(restaurant, field, value)

        await db.commit()
        return {"message": "Restaurant updated"}

@router.post("/restaurants/{restaurant_id}/suspend")
async def suspend_restaurant(
    restaurant_id: int,
    current_user: User = Depends(get_current_admin)
):
    """Suspend a restaurant service."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = result.scalar_one_or_none()

        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        restaurant.status = RestaurantStatus.SUSPENDED
        await db.commit()

        return {"message": "Restaurant suspended"}

@router.post("/restaurants/{restaurant_id}/activate")
async def activate_restaurant(
    restaurant_id: int,
    current_user: User = Depends(get_current_admin)
):
    """Activate a restaurant service."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = result.scalar_one_or_none()

        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        restaurant.status = RestaurantStatus.ACTIVE
        await db.commit()

        return {"message": "Restaurant activated"}

# --- Restaurant Owner Routes ---

@router.get("/restaurant/dashboard")
async def get_restaurant_dashboard(current_user: User = Depends(get_current_restaurant_owner)):
    """Get dashboard data for restaurant owner."""
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned")

    async with AsyncSessionLocal() as db:
        # Get restaurant info
        restaurant_result = await db.execute(
            select(Restaurant).where(Restaurant.id == current_user.restaurant_id)
        )
        restaurant = restaurant_result.scalar_one_or_none()

        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # Get today's orders
        today = datetime.utcnow().date()
        today_orders_result = await db.execute(
            select(func.count(Order.id), func.sum(Order.total_price)).where(
                and_(
                    Order.restaurant_id == restaurant.id,
                    func.date(Order.created_at) == today,
                    Order.status != OrderStatus.CANCELLED
                )
            )
        )
        today_orders, today_revenue = today_orders_result.first()
        today_orders = today_orders or 0
        today_revenue = today_revenue or 0.0

        # Get pending orders
        pending_orders_result = await db.execute(
            select(Order).where(
                and_(
                    Order.restaurant_id == restaurant.id,
                    Order.status.in_([OrderStatus.RECEIVED, OrderStatus.ACCEPTED, OrderStatus.PREPARING])
                )
            ).order_by(Order.created_at.desc()).limit(10)
        )
        pending_orders = pending_orders_result.scalars().all()

        return {
            "restaurant": {
                "id": restaurant.id,
                "name": restaurant.name,
                "status": restaurant.status.value,
                "payment_status": restaurant.payment_status.value
            },
            "today_stats": {
                "orders": today_orders,
                "revenue": today_revenue
            },
            "pending_orders": [
                {
                    "id": o.id,
                    "customer_wa_id": o.customer_wa_id,
                    "total_price": o.total_price,
                    "status": o.status.value,
                    "created_at": o.created_at.isoformat()
                } for o in pending_orders
            ]
        }

@router.post("/restaurant/items/{item_id}/toggle")
async def toggle_item_availability(
    item_id: int,
    current_user: User = Depends(get_current_restaurant_owner)
):
    """Toggle item availability (restaurant owner only)."""
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MenuItem).where(
                and_(
                    MenuItem.id == item_id,
                    MenuItem.category.has(restaurant_id=current_user.restaurant_id)
                )
            )
        )
        item = result.scalar_one_or_none()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        item.is_available = not item.is_available
        await db.commit()

        return {"message": "Item availability updated", "is_available": item.is_available}