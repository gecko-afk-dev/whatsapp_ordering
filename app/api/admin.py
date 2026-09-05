import io
import csv
import time
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query, Header, Response
import os
import re
from sqlalchemy.future import select
from sqlalchemy import func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import List, Optional, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr, Field

from app.core.database import AsyncSessionLocal, get_db
from app.core.config import settings
from app.core.auth import get_current_admin, get_current_restaurant_owner, get_current_user, get_current_cashier_or_above, get_manager_or_admin, User, get_password_hash, verify_password, create_access_token
from app.core.tier_guards import require_feature
from app.services.email import EmailService
from app.services.pdf_generator import generate_monthly_insights_report
import secrets
from app.models import (
    Restaurant, RestaurantStatus, PaymentStatus, Order, OrderStatus,
    User as UserModel, UserRole, MenuItem, AuditLog, WalletTransaction, TransactionType,
    RestaurantMessageTemplate
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Password strength validator (shared across admin endpoints)
# ---------------------------------------------------------------------------

def validate_password_strength(password: str) -> None:
    """
    Enforce minimum password strength rules.
    Raises HTTPException(400) if the password does not meet requirements.
    Rules: min 8 chars, ≥1 digit, ≥1 uppercase letter, ≥1 special character.
    """
    if (
        len(password) < 8
        or not re.search(r"\d", password)
        or not re.search(r"[A-Z]", password)
        or not re.search(r'[!@#$%^&*(),.?":{}|<>]', password)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Password does not meet strength requirements "
                "(minimum 8 characters, 1 number, 1 uppercase letter, 1 special symbol)."
            ),
        )

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
    # Meta WhatsApp Business Account ID — distinct from phone_number_id.
    # Required to submit message templates (POST /{waba_id}/message_templates).
    waba_id: Optional[str] = None
    owner_wa_id: str
    address: Optional[str] = None
    city: Optional[str] = None
    cuisine_type: Optional[str] = None
    contact_email: EmailStr

class RestaurantUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    wa_phone_number: Optional[str] = None
    api_token: Optional[str] = None
    phone_number_id: Optional[str] = None
    # Meta WhatsApp Business Account ID — distinct from phone_number_id.
    # Required to submit message templates (POST /{waba_id}/message_templates).
    waba_id: Optional[str] = None
    owner_wa_id: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    cuisine_type: Optional[str] = None
    contact_email: Optional[EmailStr] = None
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
    amount: float = Field(..., description="Transaction amount. Can be negative (-3.00 MAD micro-toll deduction) or positive (+149 MAD top-up).", example=-3.00)
    type: str = Field(..., description="Transaction type. CREDIT for top-ups, DEDUCTION for tolls/fees.", example="DEDUCTION")
    description: Optional[str] = Field(None, description="Context for the transaction.", example="Order GQ-1042 toll")
    created_at: datetime

    class Config:
        from_attributes = True

# ---------------------------------------------------------------------------
# Rate limiting — login attempts
# ---------------------------------------------------------------------------
# Mirrors the lightweight in-memory sliding-window pattern already used in
# app/api/webhook.py (message rate limiting) and app/api/flow_handler.py
# (_pin_rate_limited). Keyed by the submitted email (lowercased) so repeated
# password guesses against one account are throttled regardless of source IP.
_LOGIN_ATTEMPT_LOG: dict = {}
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5


def _login_rate_limited(email: str) -> bool:
    """Returns True if this email has exceeded the login-attempt rate limit."""
    now = time.time()
    key = email.strip().lower()
    attempts = [
        t for t in _LOGIN_ATTEMPT_LOG.get(key, [])
        if now - t < LOGIN_RATE_LIMIT_WINDOW_SECONDS
    ]
    if len(attempts) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        _LOGIN_ATTEMPT_LOG[key] = attempts
        return True
    attempts.append(now)
    _LOGIN_ATTEMPT_LOG[key] = attempts
    return False


# --- Authentication ---

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, response: Response):
    """Login for admins and restaurant owners. Sets HTTP-only secure cookie with JWT."""
    if _login_rate_limited(request.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a few minutes and try again.",
        )

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
            # Only returned when COOKIE_SECURE is off (local HTTP dev), where the
            # httpOnly cookie may not reliably reach a WS handshake. In any real
            # deployment (COOKIE_SECURE=true, the default) this MUST stay None —
            # the httpOnly cookie is the only session credential; never duplicate
            # it into a JS-readable response body. See app/api/dashboard.py's
            # websocket_endpoint, which already prefers the cookie and only
            # falls back to the bearer subprotocol when no cookie is present.
            access_token=access_token if not settings.COOKIE_SECURE else None,
            user={
                "id": user.id,
                "email": user.email,
                "role": user.role.value,
                "restaurant_id": user.restaurant_id,
                "wallet_balance": user.restaurant.wallet_balance if user.restaurant else 0.0,
                "is_accepting_orders": user.restaurant.is_accepting_orders if user.restaurant else False,
                "requires_password_change": user.requires_password_change,
                "subscription_tier": user.restaurant.subscription_tier.value if user.restaurant else "STARTER",
                "feature_flags": {
                    "overview": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_OVERVIEW_ENABLED,
                    "orders": True,
                    "menu": True,
                    "staff": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_STAFF_ENABLED,
                    "drivers": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_DRIVERS_ENABLED,
                    "audit_logs": True if user.role in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER] else settings.FEATURE_AUDIT_LOGS_ENABLED
                },
                "features": {
                    "campaigns": user.restaurant.has_feature("campaigns") if user.restaurant else (True if user.role == UserRole.ADMIN else False),
                    "smart_scheduler": user.restaurant.has_feature("smart_scheduler") if user.restaurant else (True if user.role == UserRole.ADMIN else False),
                    "crm_export": user.restaurant.has_feature("crm_export") if user.restaurant else (True if user.role == UserRole.ADMIN else False),
                    "pdf_reports": user.restaurant.has_feature("pdf_reports") if user.restaurant else (True if user.role == UserRole.ADMIN else False),
                    "multi_branch": user.restaurant.has_feature("multi_branch") if user.restaurant else (True if user.role == UserRole.ADMIN else False),
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
            validate_password_strength(updates.password)
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
            waba_id=restaurant.waba_id,
            owner_wa_id=restaurant.owner_wa_id,
            address=restaurant.address,
            city=restaurant.city,
            cuisine_type=restaurant.cuisine_type,
            contact_email=restaurant.contact_email
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
            "waba_id": r.waba_id,
            "owner_wa_id": r.owner_wa_id,
            "address": r.address,
            "city": r.city,
            "cuisine_type": r.cuisine_type,
            "status": r.status.value,
            "payment_status": r.payment_status.value,
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
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Not authorized to access restaurant billing ledger."
        )
        
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
        
        return {"message": "Successfully adjusted wallet", "wallet_balance": restaurant.wallet_balance}

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

# ── WhatsApp order-lifecycle message templates ────────────────────────────
#
# The six template bodies are platform-owned and frozen in
# app/services/message_templates.py. There is deliberately NO endpoint to edit
# them: WhatsApp classifies a template by its rendered content, so letting a
# restaurant slip promotional copy into a UTILITY template would put the WABA
# at risk. Everything below is read-only or a registration action.

@router.get("/restaurant/message-templates", response_model=dict)
async def list_message_templates(current_user: User = Depends(get_current_cashier_or_above)):
    """
    Read-only feed for the dashboard's Message Templates preview page.

    Returns the fixed catalog copy alongside this restaurant's live Meta
    approval status per template. `waba_id_missing` tells the UI to show the
    "WABA ID required — contact GEQO support" state instead of a broken list.
    """
    from app.services.message_templates import ORDER_LIFECYCLE_TEMPLATES

    if not current_user.restaurant_id:
        raise HTTPException(status_code=400, detail="User is not attached to a restaurant.")

    async with AsyncSessionLocal() as db:
        restaurant = (await db.execute(
            select(Restaurant).where(Restaurant.id == current_user.restaurant_id)
        )).scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        rows = (await db.execute(
            select(RestaurantMessageTemplate).where(
                RestaurantMessageTemplate.restaurant_id == restaurant.id
            )
        )).scalars().all()
        by_key = {r.template_key: r for r in rows}

        return {
            "waba_id_missing": not restaurant.waba_id,
            "templates": [
                {
                    "key": t["key"],
                    "label": t["label"],
                    "description": t["description"],
                    "body": t["body"],
                    "variables": t["variables"],
                    "meta_status": (
                        by_key[t["key"]].meta_status.value
                        if t["key"] in by_key else None
                    ),
                    "submitted_at": (
                        by_key[t["key"]].submitted_at.isoformat()
                        if t["key"] in by_key and by_key[t["key"]].submitted_at else None
                    ),
                }
                for t in ORDER_LIFECYCLE_TEMPLATES
            ],
        }


@router.post("/restaurant/{restaurant_id}/provision-templates", response_model=dict)
async def provision_restaurant_message_templates(
    restaurant_id: int,
    current_user: User = Depends(get_manager_or_admin)
):
    """
    Submit GEQO's six fixed order-lifecycle templates to this restaurant's WABA.

    Manual, admin-triggered action: GEQO staff click this once per restaurant
    after onboarding. Automatic submission at Embedded Signup time is out of
    scope — Embedded Signup itself does not exist yet.

    Safe to re-run: Meta's duplicate-name error is treated as already-registered,
    and a single template failing does not abort the rest of the batch.
    """
    from app.services.template_provisioning import provision_restaurant_templates

    # Non-admins may only provision their OWN restaurant.
    if current_user.role != UserRole.ADMIN and current_user.restaurant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="Not authorized for this restaurant.")

    async with AsyncSessionLocal() as db:
        restaurant = (await db.execute(
            select(Restaurant).where(Restaurant.id == restaurant_id)
        )).scalar_one_or_none()
        if not restaurant:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        try:
            results = await provision_restaurant_templates(db, restaurant)
        except ValueError as exc:
            # No waba_id set — actionable 400, not a 500.
            raise HTTPException(status_code=400, detail=str(exc))

        succeeded = [r for r in results if r.get("ok")]

        from app.services.audit import log_audit_action
        await log_audit_action(
            db=db,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            action="MESSAGE_TEMPLATES_PROVISIONED",
            target=f"restaurant_id={restaurant_id}",
            detail={
                "waba_id": restaurant.waba_id,
                "submitted": len(results),
                "succeeded": len(succeeded),
                "failed": [r["template_key"] for r in results if not r.get("ok")],
            },
            # Explicit: a platform admin provisioning on a restaurant's behalf
            # has no restaurant_id of their own, and the log belongs to the
            # restaurant that was provisioned.
            restaurant_id=restaurant_id,
        )
        await db.commit()

        return {
            "message": f"Submitted {len(succeeded)} of {len(results)} templates to Meta.",
            "results": results,
        }


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
async def list_staff(
    restaurant_id: Optional[int] = Query(default=None, description="Filter by restaurant (admin only)"),
    current_user: User = Depends(get_current_user)
):
    """List staff members. ADMIN sees all (or filtered by restaurant_id). RESTAURANT_OWNER sees only their own staff."""
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    if not settings.FEATURE_STAFF_ENABLED and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff management is currently disabled.")

    async with AsyncSessionLocal() as db:
        query = select(UserModel).where(
            UserModel.role.in_([UserRole.CASHIER, UserRole.KITCHEN_STAFF])
        )

        if current_user.role == UserRole.ADMIN:
            # Super-admin: filter by provided restaurant_id, or return all staff across all restaurants
            if restaurant_id is not None:
                query = query.where(UserModel.restaurant_id == restaurant_id)
        else:
            # RESTAURANT_OWNER: strictly scoped to their own restaurant
            if not current_user.restaurant_id:
                raise HTTPException(status_code=400, detail="No restaurant assigned to your account")
            query = query.where(UserModel.restaurant_id == current_user.restaurant_id)

        result = await db.execute(query)
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
    # Meta WhatsApp Business Account ID — distinct from phone_number_id.
    # Required to submit message templates (POST /{waba_id}/message_templates).
    waba_id: Optional[str] = None
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
            .where(BetaSignupModel.provisioned == False)  # noqa: E712
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
            waba_id=payload.waba_id,
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


# ---------------------------------------------------------------------------
# SuperAdmin Insights — CRM Export, PDF Preview & Batch Dispatch
# ---------------------------------------------------------------------------



def _build_monthly_report_pdf(
    restaurant_name: str,
    restaurant_id: int,
    city: str,
    wallet_balance: float,
    month: int,
    year: int,
    total_orders: int,
    total_gmv: float,
    total_toll: float,
    top_items: list,
    new_customers: int,
) -> bytes:
    """Generates a branded monthly PDF via fpdf2. Returns raw bytes."""
    try:
        from fpdf import FPDF
    except ImportError:
        return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"

    import calendar
    month_name = calendar.month_name[month]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(20, 20, 20)

    # Header bar
    pdf.set_fill_color(10, 10, 10)
    pdf.rect(0, 0, 210, 35, "F")
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(245, 158, 11)
    pdf.set_xy(20, 10)
    pdf.cell(0, 10, "GEQO", ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(180, 180, 180)
    pdf.set_xy(20, 22)
    pdf.cell(0, 6, "Internal Monthly Restaurant Report")
    pdf.set_xy(0, 38)

    # Title
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(20, 20, 20)
    pdf.ln(5)
    pdf.cell(0, 10, f"Monthly Report — {month_name} {year}", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, f"Restaurant: {restaurant_name}  (ID #{restaurant_id})  |  {city or 'N/A'}", ln=True)
    pdf.ln(3)

    # KPI rows
    def kpi_row(label, value, accent=False):
        pdf.set_fill_color(250, 246, 232) if accent else pdf.set_fill_color(245, 245, 245)
        pdf.set_text_color(180, 120, 10) if accent else pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(90, 9, f"  {label}", border=0, fill=True)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(80, 9, value, border=0, fill=True, ln=True)
        pdf.ln(1)

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(10, 10, 10)
    pdf.cell(0, 9, "Key Performance Indicators", ln=True)
    pdf.ln(2)
    kpi_row("Total Orders", str(total_orders))
    kpi_row("Gross Merchandise Value (GMV)", f"{total_gmv:.2f} MAD", accent=True)
    kpi_row("Platform Tolls Collected", f"{total_toll:.2f} MAD")
    kpi_row("New Customers This Month", str(new_customers))
    kpi_row("Wallet Balance (End of Month)", f"{wallet_balance:.2f} MAD", accent=wallet_balance < 0)
    pdf.ln(6)

    if top_items:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(10, 10, 10)
        pdf.cell(0, 9, "Top 5 Items This Month", ln=True)
        pdf.ln(2)
        for i, (item_name, count) in enumerate(top_items[:5], 1):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(60, 60, 60)
            pdf.set_fill_color(250, 250, 250)
            pdf.cell(10, 8, f"{i}.", fill=True)
            pdf.cell(130, 8, str(item_name)[:60], fill=True)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(10, 10, 10)
            pdf.cell(30, 8, f"x{count}", fill=True, ln=True)
            pdf.ln(1)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 6, "Generated by GEQO Analytics Engine  |  Confidential — internal use only", ln=True)
    return bytes(pdf.output())


async def _collect_restaurant_report_data(db, restaurant, month: int, year: int) -> dict:
    """Query aggregate metrics for a restaurant for a given month/year."""
    from datetime import datetime as _dt
    import calendar as _cal
    _, last_day = _cal.monthrange(year, month)
    period_start = _dt(year, month, 1)
    period_end = _dt(year, month, last_day, 23, 59, 59)

    agg = await db.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_price), 0),
        ).where(
            Order.restaurant_id == restaurant.id,
            Order.status != OrderStatus.CANCELLED,
            Order.created_at >= period_start,
            Order.created_at <= period_end,
        )
    )
    total_orders, total_gmv = agg.first()
    total_orders = int(total_orders or 0)
    total_gmv = float(total_gmv or 0)

    from app.models import OrderItem, MenuItem
    top_q = await db.execute(
        select(MenuItem.name, func.sum(OrderItem.quantity).label("qty"))
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.restaurant_id == restaurant.id,
            Order.status != OrderStatus.CANCELLED,
            Order.created_at >= period_start,
            Order.created_at <= period_end,
        )
        .group_by(MenuItem.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
    )
    top_items = [(r.name, int(r.qty)) for r in top_q.all()]

    new_cust_q = await db.execute(
        select(func.count(func.distinct(Order.customer_wa_id))).where(
            Order.restaurant_id == restaurant.id,
            Order.created_at >= period_start,
            Order.created_at <= period_end,
            Order.status != OrderStatus.CANCELLED,
        )
    )
    new_customers = int(new_cust_q.scalar() or 0)

    return {
        "total_orders": total_orders,
        "total_gmv": total_gmv,
        "total_toll": total_orders * 3.0,
        "top_items": top_items,
        "new_customers": new_customers,
    }


@router.get("/crm/export/{restaurant_id}")
async def export_crm_csv(
    restaurant_id: int,
    current_user: User = Depends(get_current_user),
    _feature_check = Depends(require_feature("crm_export")),
):
    """
    Streams a CSV of all customers for a restaurant.
    Admin: any restaurant. Owner: own restaurant only.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.role == UserRole.RESTAURANT_OWNER and current_user.restaurant_id != restaurant_id:
        raise HTTPException(status_code=403, detail="You can only export your own restaurant's CRM data")

    from app.models import Customer

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        if not r.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Restaurant not found")

        agg = await db.execute(
            select(
                Order.customer_wa_id,
                func.count(Order.id).label("order_count"),
                func.coalesce(func.sum(Order.total_price), 0).label("total_spent"),
                func.min(Order.created_at).label("first_order"),
                func.max(Order.created_at).label("last_order"),
            )
            .where(Order.restaurant_id == restaurant_id, Order.status != OrderStatus.CANCELLED)
            .group_by(Order.customer_wa_id)
            .order_by(func.count(Order.id).desc())
        )
        rows = agg.all()
        wa_ids = [row.customer_wa_id for row in rows]
        cust_q = await db.execute(
            select(Customer.wa_id, Customer.language).where(Customer.wa_id.in_(wa_ids))
        )
        customer_map = {c.wa_id: c.language for c in cust_q.all()}

    def generate_csv():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "WhatsApp Number", "Order Count", "Total Spent (MAD)",
            "First Order Date", "Last Order Date", "Opted In",
        ])
        for row in rows:
            opted_in = "Yes" if customer_map.get(row.customer_wa_id) else "No"
            writer.writerow([
                row.customer_wa_id,
                row.order_count,
                f"{float(row.total_spent):.2f}",
                row.first_order.strftime("%Y-%m-%d") if row.first_order else "",
                row.last_order.strftime("%Y-%m-%d") if row.last_order else "",
                opted_in,
            ])
        yield buf.getvalue()

    filename = f"restaurant-{restaurant_id}-crm-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/reports/preview/{restaurant_id}",
    tags=["Admin Reports"],
    summary="SuperAdmin PDF Insights Preview",
    description="Stream a preview of the monthly SuperAdmin PDF Insights report for a specific restaurant tenant."
)
async def preview_restaurant_report(
    restaurant_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(403, detail="Not authorized to preview reports.")
    
    report_data = await generate_monthly_insights_report(db, restaurant_id, month, year)
    return report_data  # Returns PDF Response or HTML Response fallback


class BatchDispatchRequest(BaseModel):
    restaurant_ids: List[int]
    month: Optional[int] = None
    year: Optional[int] = None


@router.post(
    "/reports/batch-dispatch",
    tags=["Admin Reports"],
    summary="SuperAdmin PDF Insights Batch Dispatch",
    description="Trigger a bulk background dispatch of monthly SuperAdmin PDF Insights reports to all active restaurant tenants via email or WhatsApp."
)
async def batch_dispatch_reports(
    body: BatchDispatchRequest,
    current_user: User = Depends(get_current_admin),
):
    """
    Generates + dispatches PDF monthly reports for a list of restaurants.
    Email (Resend) + WhatsApp to each owner. Partial-success safe.
    SuperAdmin only.
    """
    import base64
    import calendar as _cal
    import httpx as _httpx
    import logging as _log

    now = datetime.utcnow()
    month = body.month or now.month
    year = body.year or now.year
    month_name = _cal.month_name[month]
    _logger = _log.getLogger(__name__)

    dispatched = 0
    failed_ids: List[int] = []

    async with AsyncSessionLocal() as db:
        for rid in body.restaurant_ids:
            try:
                r = await db.execute(select(Restaurant).where(Restaurant.id == rid))
                restaurant = r.scalar_one_or_none()
                if not restaurant:
                    failed_ids.append(rid)
                    continue

                # Use the new Swiss PDF Generator
                report_resp = await generate_monthly_insights_report(db, restaurant.id, month, year)
                pdf_bytes = report_resp.body
                
                # We need some basic data for the WhatsApp notification text
                # We can do a quick query for orders count and GMV
                from sqlalchemy import func
                from app.models import Order, OrderStatus
                agg = await db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total_price), 0)).where(Order.restaurant_id == restaurant.id, Order.status != OrderStatus.CANCELLED))
                total_orders, total_gmv = agg.first()
                total_orders = int(total_orders or 0)
                total_gmv = float(total_gmv or 0.0)

                if restaurant.contact_email and settings.RESEND_API_KEY:
                    email_payload = {
                        "from": EmailService._get_from_header(),
                        "to": [restaurant.contact_email],
                        "subject": f"[GEQO] Rapport Mensuel — {month_name} {year} | {restaurant.name}",
                        "text": (
                            f"Bonjour,\n\nVeuillez trouver ci-joint votre rapport mensuel GEQO "
                            f"pour {month_name} {year}.\n\nMerci de votre confiance.\nL'équipe GEQO"
                        ),
                        "attachments": [{
                            "filename": f"geqo-rapport-{month:02d}-{year}.pdf",
                            "content": base64.b64encode(pdf_bytes).decode(),
                            "content_type": "application/pdf",
                        }],
                    }
                    async with _httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            "https://api.resend.com/emails",
                            json=email_payload,
                            headers=EmailService._get_resend_headers(),
                        )
                        resp.raise_for_status()

                if restaurant.owner_wa_id and restaurant.api_token and restaurant.phone_number_id:
                    from app.services.whatsapp import WhatsAppService
                    wa = WhatsAppService(token=restaurant.api_token, phone_id=restaurant.phone_number_id)
                    await wa.send_text_message(
                        restaurant.owner_wa_id,
                        f"📊 *Rapport GEQO — {month_name} {year}*\n\n"
                        f"Bonjour ! Votre rapport mensuel pour *{restaurant.name}* a été envoyé "
                        f"à {restaurant.contact_email}.\n\n"
                        f"📦 Commandes : {total_orders}  |  "
                        f"💰 GMV : {total_gmv:.0f} MAD  |  "
                        f"💳 Solde : {restaurant.wallet_balance:.2f} MAD",
                    )

                dispatched += 1

            except Exception:
                _logger.exception("Batch dispatch failed for restaurant_id=%s", rid)
                failed_ids.append(rid)

    return {
        "total_requested": len(body.restaurant_ids),
        "dispatched": dispatched,
        "failed": len(failed_ids),
        "failed_ids": failed_ids,
        "dispatched_at": now.isoformat() + "Z",
    }


@router.post("/reports/dispatch/{restaurant_id}")
async def dispatch_single_report(
    restaurant_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates and dispatches a PDF monthly report for a single restaurant.
    SuperAdmin only.
    """
    import base64
    import calendar as _cal
    import httpx as _httpx

    now = datetime.utcnow()
    month = month or now.month
    year = year or now.year
    month_name = _cal.month_name[month]

    r = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = r.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    report_resp = await generate_monthly_insights_report(db, restaurant.id, month, year)
    pdf_bytes = report_resp.body

    from sqlalchemy import func
    from app.models import Order, OrderStatus
    agg = await db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total_price), 0)).where(Order.restaurant_id == restaurant.id, Order.status != OrderStatus.CANCELLED))
    total_orders, total_gmv = agg.first()
    total_orders = int(total_orders or 0)
    total_gmv = float(total_gmv or 0.0)

    if restaurant.contact_email and settings.RESEND_API_KEY:
        email_payload = {
            "from": EmailService._get_from_header(),
            "to": [restaurant.contact_email],
            "subject": f"[GEQO] Rapport Mensuel — {month_name} {year} | {restaurant.name}",
            "text": (
                f"Bonjour,\n\nVeuillez trouver ci-joint votre rapport mensuel GEQO "
                f"pour {month_name} {year}.\n\nMerci de votre confiance.\nL'équipe GEQO"
            ),
            "attachments": [{
                "filename": f"geqo-rapport-{month:02d}-{year}.pdf",
                "content": base64.b64encode(pdf_bytes).decode(),
                "content_type": "application/pdf",
            }],
        }
        async with _httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                json=email_payload,
                headers=EmailService._get_resend_headers(),
            )
            resp.raise_for_status()

    if restaurant.owner_wa_id and restaurant.api_token and restaurant.phone_number_id:
        from app.services.whatsapp import WhatsAppService
        wa = WhatsAppService(token=restaurant.api_token, phone_id=restaurant.phone_number_id)
        await wa.send_text_message(
            restaurant.owner_wa_id,
            f"📊 *Rapport GEQO — {month_name} {year}*\n\n"
            f"Bonjour ! Votre rapport mensuel pour *{restaurant.name}* a été envoyé "
            f"à {restaurant.contact_email}.\n\n"
            f"📦 Commandes : {total_orders}  |  "
            f"💰 GMV : {total_gmv:.0f} MAD  |  "
            f"💳 Solde : {restaurant.wallet_balance:.2f} MAD",
        )

    return {"message": "Report dispatched successfully"}
