from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query, Header, Response
import os
from sqlalchemy.future import select
from sqlalchemy import func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import List, Optional, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr, Field

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.auth import get_current_admin, get_current_restaurant_owner, get_current_user, get_current_cashier_or_above, User, get_password_hash, verify_password, create_access_token
from app.services.email import EmailService
import secrets
from app.models import (
    Restaurant, RestaurantStatus, PaymentStatus, Order, OrderStatus,
    User as UserModel, UserRole, MenuItem, AuditLog, WalletTransaction, TransactionType
)

router = APIRouter()

# --- Pydantic Schemas ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user: dict

class RestaurantCreate(BaseModel):
    name: str
    slug: Optional[str] = None  # Auto-generated from name if omitted
    wa_phone_number: str
    api_token: Optional[str] = None  # If omitted, the platform master token is used
    phone_number_id: str
    owner_wa_id: str
    address: Optional[str] = None
    city: Optional[str] = None
    cuisine_type: Optional[str] = None
    contact_email: EmailStr
    commission_rate: float = 0.20

class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    wa_phone_number: Optional[str] = None
    api_token: Optional[str] = None
    phone_number_id: Optional[str] = None
    owner_wa_id: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    cuisine_type: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    commission_rate: Optional[float] = None
    status: Optional[RestaurantStatus] = None
    payment_status: Optional[PaymentStatus] = None

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    contact_phone: Optional[str] = None
    old_password: Optional[str] = None
    password: Optional[str] = None

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

class CreditRequest(BaseModel):
    amount: float

class BillingAdjustRequest(BaseModel):
    restaurant_id: int
    amount: float
    type: str
    description: str

class WalletTransactionResponse(BaseModel):
    id: int
    restaurant_id: int
    amount: float
    type: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# --- Authentication ---

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, response: Response):
    """Login for admins and restaurant owners. Sets HTTP-only secure cookie with JWT."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserModel)
            .options(joinedload(UserModel.restaurant))
            .where(UserModel.email == request.email)
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

        # Set HTTP-only cookie — flags are environment-aware via settings
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=30 * 60  # 30 minutes
        )

        return TokenResponse(
            access_token=None,  # Don't return token in body when using cookies
            user={
                "id": user.id,
                "email": user.email,
                "role": user.role.value,
                "restaurant_id": user.restaurant_id,
                "wallet_balance": user.restaurant.wallet_balance if user.restaurant else 0.0,
                "is_accepting_orders": user.restaurant.is_accepting_orders if user.restaurant else False,
                "requires_password_change": user.requires_password_change,
                "feature_flags": {
                    "overview": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_OVERVIEW_ENABLED,
                    "orders": True,
                    "menu": True,
                    "staff": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_STAFF_ENABLED,
                    "drivers": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_DRIVERS_ENABLED,
                    "audit_logs": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_AUDIT_LOGS_ENABLED
                }
            }
        )

@router.post("/logout")
async def logout(response: Response):
    """Logout by clearing the session cookie."""
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )
    return {"message": "Logged out successfully"}

@router.get("/me", response_model=dict)
async def get_current_session(current_user: User = Depends(get_current_user)):
    """
    Cookie-authenticated session check.
    Returns the same user dict shape as /login so the frontend
    can restore auth state on page load without re-entering credentials.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role.value,
        "restaurant_id": current_user.restaurant_id,
        "wallet_balance": current_user.restaurant.wallet_balance if current_user.restaurant else 0.0,
        "is_accepting_orders": current_user.restaurant.is_accepting_orders if current_user.restaurant else False,
        "requires_password_change": current_user.requires_password_change,
        "feature_flags": {
            "overview": True if current_user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_OVERVIEW_ENABLED,
            "orders": True,
            "menu": True,
            "staff": True if current_user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_STAFF_ENABLED,
            "drivers": True if current_user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_DRIVERS_ENABLED,
            "audit_logs": True if current_user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_AUDIT_LOGS_ENABLED,
        }
    }

@router.post("/setup-admin", response_model=dict)
async def setup_admin(x_setup_token: Optional[str] = Header(None)):
    """First-time admin setup (idempotent). Requires `SETUP_BOOTSTRAP_TOKEN` to be set in the environment
    and the same token provided via the `X-Setup-Token` header. This endpoint is disabled by default
    when `SETUP_BOOTSTRAP_TOKEN` is not configured.
    """
    env_token = os.getenv("SETUP_BOOTSTRAP_TOKEN")

    if not env_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin setup endpoint is disabled in this environment."
        )

    if not x_setup_token or x_setup_token != env_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing setup token"
        )

    async with AsyncSessionLocal() as db:
        # Check if any admin exists
        result = await db.execute(select(UserModel).where(UserModel.role == UserRole.ADMIN))
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Setup already completed. Admin user already exists."
            )

        # Create admin user with a random password; require password reset on first login
        admin_user = UserModel(
            email="admin@geqo.com",
            password_hash=get_password_hash(secrets.token_urlsafe(32)),
            role=UserRole.ADMIN,
            is_active=True,
            requires_password_change=True
        )
        db.add(admin_user)
        await db.commit()

        return {"message": "Admin account initialized successfully. Please login and complete setup."}

# --- Profile Routes ---

@router.get("/profile", response_model=dict)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile information."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role.value,
        "full_name": current_user.full_name,
        "contact_phone": current_user.contact_phone
    }

@router.put("/profile", response_model=dict)
async def update_profile(updates: ProfileUpdate, current_user: User = Depends(get_current_user)):
    """Update the current user's profile and optionally password."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(UserModel).where(UserModel.id == current_user.id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if updates.full_name is not None:
            user.full_name = updates.full_name
        if updates.contact_phone is not None:
            user.contact_phone = updates.contact_phone
            
        if updates.password:
            if not updates.old_password:
                raise HTTPException(status_code=400, detail="Old password is required to change password.")
            if not verify_password(updates.old_password, user.password_hash):
                raise HTTPException(status_code=400, detail="Incorrect old password.")
            user.password_hash = get_password_hash(updates.password)

        await db.commit()
        return {"message": "Profile updated successfully"}

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

        import re
        def _make_slug(name: str) -> str:
            s = name.lower().strip()
            s = re.sub(r'[^\w\s-]', '', s)
            s = re.sub(r'[\s_]+', '-', s)
            return re.sub(r'-+', '-', s).strip('-')

        slug = restaurant.slug or _make_slug(restaurant.name)

        # Ensure slug is unique — append suffix if needed
        base_slug = slug
        suffix = 1
        while True:
            slug_check = await db.execute(select(Restaurant).where(Restaurant.slug == slug))
            if not slug_check.scalar_one_or_none():
                break
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        new_restaurant = Restaurant(
            name=restaurant.name,
            slug=slug,
            wa_phone_number=restaurant.wa_phone_number,
            api_token=restaurant.api_token or settings.WHATSAPP_API_TOKEN,
            phone_number_id=restaurant.phone_number_id,
            owner_wa_id=restaurant.owner_wa_id,
            address=restaurant.address,
            city=restaurant.city,
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
            "wa_phone_number": r.wa_phone_number,
            "api_token": r.api_token,
            "phone_number_id": r.phone_number_id,
            "owner_wa_id": r.owner_wa_id,
            "address": r.address,
            "city": r.city,
            "cuisine_type": r.cuisine_type,
            "status": r.status.value,
            "payment_status": r.payment_status.value,
            "commission_rate": r.commission_rate,
            "wallet_balance": r.wallet_balance,
            "contact_email": r.contact_email,
            "created_at": r.created_at.isoformat() if r.created_at else None
        } for r in restaurants]

@router.get("/billing/transactions", response_model=List[WalletTransactionResponse])
async def get_billing_transactions(
    restaurant_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """Get wallet transactions. Owners see their own, admins see all or filter by restaurant."""
    async with AsyncSessionLocal() as db:
        query = select(WalletTransaction).order_by(desc(WalletTransaction.created_at))
        
        if current_user.role != UserRole.ADMIN:
            # Owners/Cashiers can only see their own
            if not current_user.restaurant_id:
                raise HTTPException(status_code=400, detail="No restaurant assigned")
            query = query.where(WalletTransaction.restaurant_id == current_user.restaurant_id)
        else:
            # Admins can optionally filter
            if restaurant_id:
                query = query.where(WalletTransaction.restaurant_id == restaurant_id)
                
        result = await db.execute(query)
        transactions = result.scalars().all()
        
        # Convert Enum to string for the response
        resp = []
        for t in transactions:
            resp.append(WalletTransactionResponse(
                id=t.id,
                restaurant_id=t.restaurant_id,
                amount=t.amount,
                type=t.type.value,
                description=t.description,
                created_at=t.created_at
            ))
        return resp

@router.post("/billing/adjust")
async def adjust_billing(
    request: BillingAdjustRequest,
    current_user: User = Depends(get_current_admin)
):
    """Adjust a restaurant's wallet balance manually (Admin only)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Restaurant).where(Restaurant.id == request.restaurant_id))
        restaurant = result.scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        
        try:
            tx_type = TransactionType(request.type.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid transaction type")
            
        restaurant.wallet_balance += request.amount
        
        transaction = WalletTransaction(
            restaurant_id=restaurant.id,
            amount=request.amount,
            type=tx_type,
            description=request.description
        )
        db.add(transaction)
        
        from app.services.audit import log_audit_action
        await log_audit_action(
            db=db,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            action="BILLING_ADJUSTED",
            target=f"restaurant_id={restaurant.id}",
            detail={"amount": request.amount, "type": request.type, "description": request.description},
            restaurant_id=restaurant.id
        )
        
        await db.commit()
        
        return {"message": f"Successfully adjusted wallet", "wallet_balance": restaurant.wallet_balance}

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
async def get_restaurant_dashboard(current_user: User = Depends(get_current_cashier_or_above)):
    """Get dashboard data for restaurant staff and owner."""
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

        from app.services.hours import is_restaurant_open
        return {
            "restaurant": {
                "id": restaurant.id,
                "name": restaurant.name,
                "status": restaurant.status.value,
                "is_accepting_orders": restaurant.is_accepting_orders,
                "is_open": is_restaurant_open(restaurant),
                "payment_status": restaurant.payment_status.value,
                "wallet_balance": restaurant.wallet_balance,
                "latitude": restaurant.latitude,
                "longitude": restaurant.longitude,
                "max_delivery_radius_km": restaurant.max_delivery_radius_km,
                "base_delivery_fee": restaurant.base_delivery_fee,
                "per_km_delivery_fee": restaurant.per_km_delivery_fee,
                "operating_hours": restaurant.operating_hours,
                "city": restaurant.city,
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


# --- Staff Management & Audit Log Schemas & Endpoints ---

class StaffInviteRequest(BaseModel):
    email: EmailStr
    role: UserRole

class StaffResponse(BaseModel):
    id: int
    email: EmailStr
    role: str
    is_active: bool
    requires_password_change: bool

    class Config:
        from_attributes = True

class AuditLogResponse(BaseModel):
    id: int
    restaurant_id: Optional[int]
    actor_user_id: Optional[int]
    actor_email: EmailStr
    action: str
    target: Optional[str]
    detail: Optional[Any]
    created_at: datetime

    class Config:
        from_attributes = True

async def write_audit_log(
    db: AsyncSession,
    user: UserModel,
    action: str,
    target: Optional[str] = None,
    detail: Optional[str] = None
):
    """Helper to record audit log entry inside the database."""
    detail_data = {"message": detail} if detail else None
    log_entry = AuditLog(
        restaurant_id=user.restaurant_id,
        actor_user_id=user.id,
        actor_email=user.email,
        action=action,
        target=target,
        detail=detail_data
    )
    db.add(log_entry)
    await db.commit()

@router.get("/staff", response_model=List[StaffResponse])
async def list_staff(current_user: User = Depends(get_current_restaurant_owner)):
    """List all staff members for the restaurant owner's restaurant."""
    if not settings.FEATURE_STAFF_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff management is currently disabled.")
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned to your account")
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserModel).where(
                and_(
                    UserModel.restaurant_id == current_user.restaurant_id,
                    UserModel.role.in_([UserRole.CASHIER, UserRole.KITCHEN_STAFF])
                )
            )
        )
        staff = result.scalars().all()
        return staff

@router.post("/staff/invite", response_model=dict)
async def invite_staff(
    request: StaffInviteRequest,
    current_user: User = Depends(get_current_restaurant_owner)
):
    """Invite a new cashier or kitchen staff member by email."""
    if not settings.FEATURE_STAFF_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff management is currently disabled.")
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned to your account")

    if request.role not in [UserRole.CASHIER, UserRole.KITCHEN_STAFF]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. You can only invite Cashier or Kitchen Staff."
        )

    async with AsyncSessionLocal() as db:
        # Check if email already exists
        existing = await db.execute(select(UserModel).where(UserModel.email == request.email))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        setup_token = secrets.token_urlsafe(32)
        # Create user record with a temporary random password
        new_staff = UserModel(
            email=request.email,
            password_hash=get_password_hash(secrets.token_hex(16)),
            role=request.role,
            restaurant_id=current_user.restaurant_id,
            is_active=True,
            reset_token=setup_token,
            reset_token_expiry=datetime.utcnow() + timedelta(days=7),
            requires_password_change=True
        )
        db.add(new_staff)
        await db.commit()
        await db.refresh(new_staff)

        # Write audit log
        await write_audit_log(
            db=db,
            user=current_user,
            action="STAFF_INVITED",
            target=f"user_id={new_staff.id}",
            detail=f"Invited staff user {new_staff.email} as {new_staff.role.value}"
        )

        # Send the setup/invite email
        await EmailService.send_staff_invite_email(new_staff.email, new_staff.role.value, setup_token)

        return {"message": f"Staff invited successfully. Invite email sent to {new_staff.email}."}

@router.post("/staff/{user_id}/toggle", response_model=dict)
async def toggle_staff_status(
    user_id: int,
    current_user: User = Depends(get_current_restaurant_owner)
):
    """Toggle a staff member's active status."""
    if not settings.FEATURE_STAFF_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff management is currently disabled.")
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned to your account")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserModel).where(
                and_(
                    UserModel.id == user_id,
                    UserModel.restaurant_id == current_user.restaurant_id,
                    UserModel.role.in_([UserRole.CASHIER, UserRole.KITCHEN_STAFF])
                )
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Staff user not found")

        # Toggle active status
        user.is_active = not user.is_active
        await db.commit()

        status_text = "activated" if user.is_active else "deactivated"
        
        # Write audit log
        await write_audit_log(
            db=db,
            user=current_user,
            action="STAFF_STATUS_TOGGLED",
            target=f"user_id={user.id}",
            detail=f"Staff user {user.email} status set to {status_text}"
        )

        return {"message": f"Staff user has been {status_text}.", "is_active": user.is_active}

@router.delete("/staff/{user_id}", response_model=dict)
async def remove_staff(
    user_id: int,
    current_user: User = Depends(get_current_restaurant_owner)
):
    """Permanently delete a staff member from the restaurant."""
    if not settings.FEATURE_STAFF_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff management is currently disabled.")
    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="No restaurant assigned to your account")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserModel).where(
                and_(
                    UserModel.id == user_id,
                    UserModel.restaurant_id == current_user.restaurant_id,
                    UserModel.role.in_([UserRole.CASHIER, UserRole.KITCHEN_STAFF])
                )
            )
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Staff user not found")

        email = user.email
        await db.delete(user)
        await db.commit()

        # Write audit log
        await write_audit_log(
            db=db,
            user=current_user,
            action="STAFF_REMOVED",
            target=f"user_id={user_id}",
            detail=f"Removed staff user {email}"
        )

        return {"message": "Staff member successfully removed."}

@router.get("/audit-log", response_model=List[AuditLogResponse])
async def get_audit_log(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user)
):
    """Retrieve audit logs. Owners see their own restaurant's logs; Admins see all logs."""
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    
    if not settings.FEATURE_AUDIT_LOGS_ENABLED and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Audit logs are currently disabled.")

    async with AsyncSessionLocal() as db:
        query = select(AuditLog)
        if current_user.role == UserRole.RESTAURANT_OWNER:
            if not current_user.restaurant_id:
                raise HTTPException(status_code=400, detail="No restaurant assigned to your account")
            query = query.where(AuditLog.restaurant_id == current_user.restaurant_id)
        
        query = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)
        res = await db.execute(query)
        logs = res.scalars().all()
        return logs


# --- Beta Leads & 1-Click Provisioning ---

class BetaSignupResponse(BaseModel):
    id: int
    manager_name: str
    restaurant_name: str
    email: str
    whatsapp_number: str
    locale: str
    created_at: datetime
    card_code: str
    confirmation_sent: bool

    class Config:
        from_attributes = True


class ProvisionRequest(BaseModel):
    phone_number_id: str = Field(..., min_length=1)
    wa_phone_number: str = Field(..., pattern=r"^\+?[0-9]{9,15}$")
    owner_wa_id: Optional[str] = None


@router.get("/beta-signups", response_model=List[BetaSignupResponse])
async def list_pending_beta_signups(
    current_user: User = Depends(get_current_admin)
):
    """
    Returns all beta signups that have NOT yet been provisioned into restaurants.
    Restricted to super-admin only.
    """
    async with AsyncSessionLocal() as db:
        from sqlalchemy.orm import joinedload
        from app.models import BetaSignup as BetaSignupModel

        result = await db.execute(
            select(BetaSignupModel)
            .options(joinedload(BetaSignupModel.card))
            .where(BetaSignupModel.provisioned == False)
            .order_by(BetaSignupModel.created_at.desc())
        )
        signups = result.scalars().all()

        return [
            {
                "id": s.id,
                "manager_name": s.manager_name,
                "restaurant_name": s.restaurant_name,
                "email": s.email,
                "whatsapp_number": s.whatsapp_number,
                "locale": s.locale,
                "created_at": s.created_at,
                "card_code": s.card.card_code if s.card else "",
                "confirmation_sent": s.confirmation_sent,
            }
            for s in signups
        ]


@router.post("/beta-signups/{signup_id}/provision", response_model=dict)
async def provision_beta_signup(
    signup_id: int,
    payload: ProvisionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_admin),
):
    """
    1-click provisioning: converts a pending beta signup into a live restaurant
    with a new owner account and sends the setup invite email.
    """
    from sqlalchemy.orm import joinedload
    from app.models import BetaSignup as BetaSignupModel

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(BetaSignupModel)
            .options(joinedload(BetaSignupModel.card))
            .where(BetaSignupModel.id == signup_id)
        )
        signup = result.scalar_one_or_none()

        if not signup:
            raise HTTPException(status_code=404, detail="Beta signup not found")
        if signup.provisioned:
            raise HTTPException(status_code=409, detail="This lead has already been provisioned")

        existing_user = await db.execute(
            select(UserModel).where(UserModel.email == signup.email)
        )
        if existing_user.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"A user with email {signup.email} already exists"
            )

        existing_phone = await db.execute(
            select(Restaurant).where(Restaurant.wa_phone_number == payload.wa_phone_number)
        )
        if existing_phone.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="This WhatsApp number is already registered to another restaurant"
            )

        new_restaurant = Restaurant(
            name=signup.restaurant_name,
            wa_phone_number=payload.wa_phone_number,
            api_token=settings.WHATSAPP_API_TOKEN,
            phone_number_id=payload.phone_number_id,
            owner_wa_id=payload.owner_wa_id or signup.whatsapp_number,
            contact_email=signup.email,
            status=RestaurantStatus.ACTIVE,
        )
        db.add(new_restaurant)
        await db.flush()

        setup_token = secrets.token_urlsafe(32)
        new_owner = UserModel(
            email=signup.email,
            password_hash=get_password_hash(secrets.token_hex(16)),
            role=UserRole.RESTAURANT_OWNER,
            restaurant_id=new_restaurant.id,
            reset_token=setup_token,
            reset_token_expiry=datetime.utcnow() + timedelta(days=7),
            requires_password_change=True,
            is_active=True,
        )
        db.add(new_owner)

        signup.provisioned = True

        await db.commit()

        background_tasks.add_task(
            EmailService.send_invite_email,
            signup.email,
            setup_token,
        )

        await write_audit_log(
            db=db,
            user=current_user,
            action="BETA_SIGNUP_PROVISIONED",
            target=f"signup_id={signup_id},restaurant_id={new_restaurant.id}",
            detail=f"Provisioned {signup.restaurant_name} ({signup.email}) from beta lead",
        )

    return {
        "message": "Restaurant provisioned successfully. Invite email is on its way.",
        "restaurant_id": new_restaurant.id,
    }