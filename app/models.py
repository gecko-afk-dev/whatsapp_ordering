from __future__ import annotations
from datetime import datetime
from enum import Enum as PyEnum
import secrets
import string

def generate_tracking_code():
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
from typing import List, Optional
from sqlalchemy import ForeignKey, String, DateTime, Float, Text, Enum, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

class Base(DeclarativeBase):
    pass

# --- Enums ---

class OrderStatus(PyEnum):
    PENDING = "pending"
    RECEIVED = "received"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class FulfillmentMethod(PyEnum):
    DELIVERY = "delivery"
    PICKUP = "pickup"

class ModifierGroupType(str, PyEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    EXCLUSION = "exclusion"

class TransactionType(PyEnum):
    CREDIT = "credit"
    DEBIT = "debit"
    CORRECTION = "correction"

class UserRole(PyEnum):
    ADMIN = "admin"
    RESTAURANT_OWNER = "restaurant_owner"
    CASHIER = "cashier"
    KITCHEN_STAFF = "kitchen_staff"

class RestaurantStatus(PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"

class PaymentStatus(PyEnum):
    PAID = "paid"
    OVERDUE = "overdue"
    SUSPENDED = "suspended"

class BetaCardStatus(PyEnum):
    AVAILABLE = "available"    # Printed, not yet scanned
    CLAIMED = "claimed"        # Assigned to a restaurant
    REVOKED = "revoked"        # Invalidated manually

class SubscriptionTier(PyEnum):
    STARTER = "STARTER"
    PRO = "PRO"
    SCALE = "SCALE"
    MULTI = "MULTI"

class DataDeletionStatus(PyEnum):
    PENDING = "pending"      # Received, within the 30-day CNDP SLA window
    COMPLETED = "completed"  # Erasure performed and confirmed by an admin

# --- Tables ---

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    restaurant: Mapped["Restaurant"] = relationship()

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    is_active: Mapped[bool] = mapped_column(default=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # For restaurant owners
    restaurant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("restaurants.id"))
    restaurant: Mapped[Optional["Restaurant"]] = relationship(back_populates="owner")
    
    # Password Reset & Setup
    reset_token: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reset_token_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    requires_password_change: Mapped[bool] = mapped_column(default=False)

class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    wa_phone_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    api_token: Mapped[str] = mapped_column(Text)
    phone_number_id: Mapped[str] = mapped_column(String(50))
    owner_wa_id: Mapped[str] = mapped_column(String(20))
    
    # Geo-Fencing & Delivery Fields
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_delivery_radius_km: Mapped[float] = mapped_column(Float, default=10.0, doc="Maximum allowable delivery radius in kilometers for Haversine geo-fencing")
    base_delivery_fee: Mapped[float] = mapped_column(Float, default=10.0)
    per_km_delivery_fee: Mapped[float] = mapped_column(Float, default=2.0)

    # New fields for Phase 1
    status: Mapped[RestaurantStatus] = mapped_column(Enum(RestaurantStatus), default=RestaurantStatus.ACTIVE)
    subscription_tier: Mapped[SubscriptionTier] = mapped_column(Enum(SubscriptionTier), default=SubscriptionTier.STARTER, doc="Current GEQO platform subscription tier (STARTER, PRO, SCALE, MULTI)")
    is_accepting_orders: Mapped[bool] = mapped_column(default=True, doc="Boolean flag controlling whether the restaurant can receive new inbound checkout requests")
    payment_status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PAID)
    wallet_balance: Mapped[float] = mapped_column(Float, default=0.0, doc="Prepaid wallet balance in MAD. Deducted atomically during checkout (-3.00 MAD) for micro-tolls")
    address: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    cuisine_type: Mapped[Optional[str]] = mapped_column(String(50))
    operating_hours: Mapped[Optional[str]] = mapped_column(Text)  # JSON string
    contact_email: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_payment_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    categories: Mapped[List["Category"]] = relationship(back_populates="restaurant")
    drivers: Mapped[List["Driver"]] = relationship(back_populates="restaurant")
    orders: Mapped[List["Order"]] = relationship(back_populates="restaurant")
    owner: Mapped[Optional["User"]] = relationship(back_populates="restaurant")

    def max_delivery_agents(self) -> int:
        if self.subscription_tier == SubscriptionTier.STARTER:
            return 2
        if self.subscription_tier == SubscriptionTier.PRO:
            return 5
        return 999
        
    def max_kds_screens(self) -> int:
        if self.subscription_tier == SubscriptionTier.STARTER:
            return 1
        if self.subscription_tier == SubscriptionTier.PRO:
            return 2
        return 999
        
    def has_feature(self, feature_name: str) -> bool:
        if feature_name in ["pwa_menu", "dispatch", "pin_verification", "geo_fencing"]:
            return True
        if feature_name == "multi_branch":
            return self.subscription_tier == SubscriptionTier.MULTI
        if feature_name in ["campaigns", "smart_scheduler", "crm_export", "pdf_reports"]:
            return self.subscription_tier in (SubscriptionTier.SCALE, SubscriptionTier.MULTI)
        return False

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    language: Mapped[Optional[str]] = mapped_column(String(5))
    ctwa_free_window_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    marketing_opt_in: Mapped[bool] = mapped_column(
        default=False,
        doc="Consent to receive marketing/promotional WhatsApp messages. "
            "Captured at PWA checkout, unchecked by default (CNDP-compliant "
            "opt-in, not opt-out). Independent of data-deletion requests — "
            "opting out of marketing does NOT delete the customer's data; "
            "see DataDeletionRequest for that separate flow."
    )

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    restaurant: Mapped["Restaurant"] = relationship(back_populates="categories")
    items: Mapped[List["MenuItem"]] = relationship(back_populates="category", cascade="all, delete-orphan")
    modifier_groups: Mapped[List["ModifierGroup"]] = relationship(back_populates="category", cascade="all, delete-orphan")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    is_available: Mapped[bool] = mapped_column(default=True)
    item_details: Mapped[Optional[str]] = mapped_column(Text)  # Ingredients list
    image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    allows_exclusions: Mapped[bool] = mapped_column(default=False)  # For items like sandwiches
    
    category: Mapped["Category"] = relationship(back_populates="items")
    modifier_groups: Mapped[List["ModifierGroup"]] = relationship(back_populates="menu_item", cascade="all, delete-orphan")

class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("menu_items.id"), nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    min_selection: Mapped[int] = mapped_column(default=0)
    max_selection: Mapped[int] = mapped_column(default=1)
    group_type: Mapped[str] = mapped_column(String(20), default="optional")
    menu_item: Mapped[Optional["MenuItem"]] = relationship(back_populates="modifier_groups")
    category: Mapped[Optional["Category"]] = relationship(back_populates="modifier_groups")
    options: Mapped[List["ModifierOption"]] = relationship(back_populates="group", cascade="all, delete-orphan")

class ModifierOption(Base):
    __tablename__ = "modifier_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    price_override: Mapped[float] = mapped_column(default=0.0)
    is_available: Mapped[bool] = mapped_column(default=True)
    
    group: Mapped["ModifierGroup"] = relationship(back_populates="options")

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, default=generate_tracking_code)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_wa_id: Mapped[str] = mapped_column(String(20), index=True)
    fulfillment_method: Mapped[FulfillmentMethod] = mapped_column(Enum(FulfillmentMethod))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    driver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("drivers.id"))
    delivery_pin: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True)
    delivery_fee: Mapped[float] = mapped_column(Float, default=0.0)
    customer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        doc="Timestamp this specific order's Terms of Service checkbox was "
            "accepted. Stored per-order (not just per-customer) so it stands "
            "as its own evidence of a valid electronic contract under Law "
            "53-05, independent of whether the customer's consent later changes."
    )

    # Use strings "Restaurant" etc. to avoid NameErrors
    restaurant: Mapped["Restaurant"] = relationship(back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    quantity: Mapped[int] = mapped_column(default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    
    order: Mapped["Order"] = relationship(back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship()
    exclusions: Mapped[List["OrderItemExclusion"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")
    modifiers: Mapped[List["OrderItemModifier"]] = relationship(back_populates="order_item", cascade="all, delete-orphan")

class OrderItemExclusion(Base):
    __tablename__ = "order_item_exclusions"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id", ondelete="CASCADE"))
    ingredient_name: Mapped[str] = mapped_column(String(100))  # e.g., "lettuce", "tomato"
    
    order_item: Mapped["OrderItem"] = relationship(back_populates="exclusions")

class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id", ondelete="CASCADE"))
    modifier_option_id: Mapped[int] = mapped_column(ForeignKey("modifier_options.id"))
    
    order_item: Mapped["OrderItem"] = relationship(back_populates="modifiers")
    modifier_option: Mapped["ModifierOption"] = relationship()

class Driver(Base):
    __tablename__ = "drivers"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    name: Mapped[str] = mapped_column(String(100))
    wa_id: Mapped[str] = mapped_column(String(20), unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    
    restaurant: Mapped["Restaurant"] = relationship(back_populates="drivers")

class Cart(Base):
    __tablename__ = "carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_wa_id: Mapped[str] = mapped_column(String(20))
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    restaurant: Mapped["Restaurant"] = relationship()
    items: Mapped[List["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")

class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"))
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    quantity: Mapped[int] = mapped_column(default=1)
    
    cart: Mapped["Cart"] = relationship(back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship()
    modifiers: Mapped[List["CartItemModifier"]] = relationship(back_populates="cart_item", cascade="all, delete-orphan")
    exclusions: Mapped[List["CartItemExclusion"]] = relationship(back_populates="cart_item", cascade="all, delete-orphan")

class CartItemExclusion(Base):
    __tablename__ = "cart_item_exclusions"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_item_id: Mapped[int] = mapped_column(ForeignKey("cart_items.id", ondelete="CASCADE"))
    ingredient_name: Mapped[str] = mapped_column(String(100))
    
    cart_item: Mapped["CartItem"] = relationship(back_populates="exclusions")

class CartItemModifier(Base):
    __tablename__ = "cart_item_modifiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_item_id: Mapped[int] = mapped_column(ForeignKey("cart_items.id", ondelete="CASCADE"))
    modifier_option_id: Mapped[int] = mapped_column(ForeignKey("modifier_options.id"))
    
    cart_item: Mapped["CartItem"] = relationship(back_populates="modifiers")
    modifier_option: Mapped["ModifierOption"] = relationship()

class DailyAnalytics(Base):
    __tablename__ = "daily_analytics"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    
    total_orders: Mapped[int] = mapped_column(default=0)
    total_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    avg_order_value: Mapped[float] = mapped_column(Float, default=0.0)
    unique_customers: Mapped[int] = mapped_column(default=0)
    
    restaurant: Mapped["Restaurant"] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("restaurants.id"), nullable=True, index=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), index=True)  # e.g. ORDER_STATUS_UPDATED
    target: Mapped[Optional[str]] = mapped_column(String(100))    # e.g. order_id=42
    detail: Mapped[Optional[dict]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))            # structured JSON data
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class BetaCard(Base):
    __tablename__ = "beta_cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    status: Mapped[BetaCardStatus] = mapped_column(Enum(BetaCardStatus), default=BetaCardStatus.AVAILABLE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trial_days: Mapped[int] = mapped_column(
        default=14,
        doc="Trial length granted when this specific card is claimed. Publicly "
            "distributed cards default to 14 days; hand-pitched MVP-launch "
            "cards can be set to 30 by updating this column for that card "
            "before it's handed out. Snapshotted onto BetaSignup.trial_ends_at "
            "at claim time, so later changing this default doesn't retroactively "
            "affect already-claimed signups."
    )
    signup: Mapped[Optional["BetaSignup"]] = relationship(back_populates="card")

class BetaSignup(Base):
    __tablename__ = "beta_signups"
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("beta_cards.id"), unique=True)
    manager_name: Mapped[str] = mapped_column(String(150))
    restaurant_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(255), index=True)
    whatsapp_number: Mapped[str] = mapped_column(String(20))
    locale: Mapped[str] = mapped_column(String(5), default="fr")  # en, fr, ar
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    confirmation_sent: Mapped[bool] = mapped_column(default=False)
    provisioned: Mapped[bool] = mapped_column(default=False)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        doc="Snapshot of card.trial_days added to the claim timestamp. Tracking "
            "only for now — nothing currently gates on this expiring; add "
            "enforcement (dashboard banner, WhatsApp reminder, order block, "
            "etc.) once the desired behavior at trial-end is decided."
    )
    card: Mapped["BetaCard"] = relationship(back_populates="signup")


class DataDeletionRequest(Base):
    """
    CNDP Law 09-08 erasure request audit trail. Created by
    POST /api/v1/public/data-deletion-request. Not tenant-scoped — a
    customer's phone number may have ordered from multiple restaurants,
    so fulfillment is a platform-level admin action, not a per-restaurant one.
    """
    __tablename__ = "data_deletion_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # native_enum=False: stored as VARCHAR + CHECK constraint, matching this repo's
    # existing precedent for subscription_tier (see migrate_add_subscription_tier.py) —
    # avoids a Postgres CREATE TYPE/ALTER TYPE dependency for a low-cardinality status field.
    status: Mapped[DataDeletionStatus] = mapped_column(Enum(DataDeletionStatus, native_enum=False, length=20), default=DataDeletionStatus.PENDING, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Analytics — raw_l1 instrumentation layer
# ---------------------------------------------------------------------------

import uuid as _uuid

class EventLog(Base):
    """
    Append-only event ledger for the GEQO Internal Insights Engine.
    Lives in the raw_l1 PostgreSQL schema (isolated from operational tables).
    Never FK-constrained to operational tables — decoupled analytics store.
    """
    __tablename__ = "event_logs"
    __table_args__ = {"schema": "raw_l1"}

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(_uuid.uuid4())
    )
    # Client-supplied idempotency key — prevents duplicate events on retry
    event_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True, unique=True
    )
    # e.g. "order.placed", "wallet.toll_charged", "menu.viewed"
    event_type: Mapped[str] = mapped_column(String(60), index=True, doc="Phase A Analytics: Primary action identifier (e.g., order.placed, wallet.toll_charged)")
    # Tenant scoping — intentionally no FK to allow historical data survival
    restaurant_id: Mapped[Optional[int]] = mapped_column(nullable=True, index=True)
    # SHA-256(phone.strip() + salt) — pseudonymized at source, never raw PII
    customer_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True, doc="Phase A Analytics: Pseudonymized SHA-256 customer identifier for tracking behavior without raw PII")
    # Origin channel: "whatsapp" | "pwa" | "kds" | "system"
    channel: Mapped[str] = mapped_column(String(20), doc="Phase A Analytics: Origination platform (e.g., whatsapp, pwa, kds)")
    # Typed event context — arbitrary structured payload
    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True, doc="Phase A Analytics: Arbitrary structured context payload for the event"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True
    )