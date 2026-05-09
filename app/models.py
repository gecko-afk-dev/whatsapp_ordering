from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import List, Optional
from sqlalchemy import ForeignKey, String, DateTime, Float, Boolean, Text, Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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

class UserRole(PyEnum):
    ADMIN = "admin"
    RESTAURANT_OWNER = "restaurant_owner"

class RestaurantStatus(PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"

class PaymentStatus(PyEnum):
    PAID = "paid"
    OVERDUE = "overdue"
    SUSPENDED = "suspended"

# --- Tables ---

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # For restaurant owners
    restaurant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("restaurants.id"))
    restaurant: Mapped[Optional["Restaurant"]] = relationship(back_populates="owner")

class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    wa_phone_number: Mapped[str] = mapped_column(String(20), unique=True)
    api_token: Mapped[str] = mapped_column(Text)
    phone_number_id: Mapped[str] = mapped_column(String(50))
    owner_wa_id: Mapped[str] = mapped_column(String(20))
    
    # New fields for Phase 1
    status: Mapped[RestaurantStatus] = mapped_column(Enum(RestaurantStatus), default=RestaurantStatus.ACTIVE)
    payment_status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PAID)
    commission_rate: Mapped[float] = mapped_column(Float, default=0.20)  # 20%
    address: Mapped[Optional[str]] = mapped_column(String(255))
    cuisine_type: Mapped[Optional[str]] = mapped_column(String(50))
    operating_hours: Mapped[Optional[str]] = mapped_column(Text)  # JSON string
    contact_email: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_payment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    categories: Mapped[List["Category"]] = relationship(back_populates="restaurant")
    drivers: Mapped[List["Driver"]] = relationship(back_populates="restaurant")
    orders: Mapped[List["Order"]] = relationship(back_populates="restaurant")
    owner: Mapped[Optional["User"]] = relationship(back_populates="restaurant")

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    language: Mapped[Optional[str]] = mapped_column(String(5))

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    
    restaurant: Mapped["Restaurant"] = relationship(back_populates="categories")
    items: Mapped[List["MenuItem"]] = relationship(back_populates="category")

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
    allows_exclusions: Mapped[bool] = mapped_column(default=False)  # For items like sandwiches
    
    category: Mapped["Category"] = relationship(back_populates="items")
    modifier_groups: Mapped[List["ModifierGroup"]] = relationship(back_populates="menu_item")

class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    min_selection: Mapped[int] = mapped_column(default=0)
    max_selection: Mapped[int] = mapped_column(default=1)
    
    menu_item: Mapped["MenuItem"] = relationship(back_populates="modifier_groups")
    options: Mapped[List["ModifierOption"]] = relationship(back_populates="group")

class ModifierOption(Base):
    __tablename__ = "modifier_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"))
    name_en: Mapped[str] = mapped_column(String(100))
    name_ar: Mapped[str] = mapped_column(String(100))
    name_fr: Mapped[str] = mapped_column(String(100))
    price_override: Mapped[float] = mapped_column(default=0.0)
    
    group: Mapped["ModifierGroup"] = relationship(back_populates="options")

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    customer_wa_id: Mapped[str] = mapped_column(String(20))
    fulfillment_method: Mapped[FulfillmentMethod] = mapped_column(Enum(FulfillmentMethod))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    driver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("drivers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
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

class OrderItemExclusion(Base):
    __tablename__ = "order_item_exclusions"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id", ondelete="CASCADE"))
    ingredient_name: Mapped[str] = mapped_column(String(100))  # e.g., "lettuce", "tomato"
    
    order_item: Mapped["OrderItem"] = relationship(back_populates="exclusions")

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
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
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"))
    
    total_orders: Mapped[int] = mapped_column(default=0)
    total_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    avg_order_value: Mapped[float] = mapped_column(Float, default=0.0)
    unique_customers: Mapped[int] = mapped_column(default=0)
    
    restaurant: Mapped["Restaurant"] = relationship()