import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, patch

import asyncio

# Override the database URL before importing the app
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5432/whatsapp_ordering_test"
)

# Test Postgres connection and fallback to SQLite if needed
async def check_pg_connection():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect():
            pass
        return True
    except Exception as e:
        print(f"PostgreSQL connection failed: {e}. Falling back to SQLite.")
        return False
    finally:
        await engine.dispose()

is_pg_available = asyncio.run(check_pg_connection())

if not is_pg_available:
    TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
    
    # Mock with_for_update for SQLite
    from sqlalchemy.sql.selectable import Select
    def mock_with_for_update(self, *args, **kwargs):
        return self
    Select.with_for_update = mock_with_for_update
# Set up mock environment variables for tests
os.environ["WHATSAPP_API_TOKEN"] = "test_token"
os.environ["PHONE_NUMBER_ID"] = "test_phone_id"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "1158201444"
os.environ["WHATSAPP_FLOW_ID"] = "test_flow_id"
os.environ["DRIVER_FLOW_ID"] = "test_driver_flow_id"
os.environ["WHATSAPP_APP_SECRET"] = "test_secret"
os.environ["SECRET_KEY"] = "test_jwt_secret"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# We must import Base and models after setting the environment
from app.models import (
    Base, Restaurant, User, UserRole, Category, MenuItem, ModifierGroup, ModifierOption, RestaurantStatus
)
from app.core.auth import create_access_token
from app.main import app

from sqlalchemy.pool import StaticPool

# Create a test engine
test_engine_kwargs = {"echo": False}
if "sqlite" in TEST_DATABASE_URL:
    test_engine_kwargs["poolclass"] = StaticPool
    test_engine_kwargs["connect_args"] = {"check_same_thread": False}

test_engine = create_async_engine(TEST_DATABASE_URL, **test_engine_kwargs)
TestingSessionLocal = sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    # Create all tables once for the test session
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Optionally drop tables or keep them for manual inspection
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture()
async def db_session():
    """Yields a database session. Uses a nested transaction to rollback after the test."""
    async with test_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()
        
        # Use the connection for the session
        async_session = AsyncSession(conn, expire_on_commit=False)
        
        # Monkeypatch the app's AsyncSessionLocal to use our session
        with patch('app.api.admin.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.webhook.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.public_menu.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.public_orders.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.dashboard.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.menu.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.drivers.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.auth.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.beta.AsyncSessionLocal', return_value=async_session), \
             patch('app.api.flow_handler.AsyncSessionLocal', return_value=async_session), \
             patch('app.core.auth.AsyncSessionLocal', return_value=async_session), \
             patch('app.core.database.AsyncSessionLocal', return_value=async_session):
            
            yield async_session
            
        await async_session.close()
        await conn.rollback()

@pytest_asyncio.fixture()
async def async_client(db_session):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

@pytest_asyncio.fixture()
async def seed_restaurant(db_session):
    owner = User(
        email="owner@example.com",
        password_hash="fakehash",
        role=UserRole.RESTAURANT_OWNER
    )
    admin = User(
        email="admin@example.com",
        password_hash="fakehash",
        role=UserRole.ADMIN
    )
    cashier = User(
        email="cashier@example.com",
        password_hash="fakehash",
        role=UserRole.CASHIER
    )
    staff = User(
        email="staff@example.com",
        password_hash="fakehash",
        role=UserRole.KITCHEN_STAFF
    )
    db_session.add_all([owner, admin, cashier, staff])
    await db_session.flush()

    restaurant = Restaurant(
        name="Test Restaurant",
        slug="test-restaurant",
        wa_phone_number="123456789",
        api_token="fake_token",
        phone_number_id="fake_phone_id",
        owner_wa_id="987654321",
        max_delivery_radius_km=5.0,
        base_delivery_fee=10.0,
        per_km_delivery_fee=2.0,
        status=RestaurantStatus.ACTIVE,
        is_accepting_orders=True,
        wallet_balance=50.0,
        latitude=34.020882,
        longitude=-6.841650
    )
    db_session.add(restaurant)
    await db_session.flush()
    
    owner.restaurant_id = restaurant.id
    await db_session.commit()
    return restaurant

@pytest_asyncio.fixture()
async def seed_menu(db_session, seed_restaurant):
    category = Category(
        restaurant_id=seed_restaurant.id,
        name_en="Burgers",
        name_ar="برجر",
        name_fr="Burgers"
    )
    db_session.add(category)
    await db_session.flush()
    
    menu_item = MenuItem(
        category_id=category.id,
        name_en="Classic Burger",
        name_ar="برجر كلاسيك",
        name_fr="Burger Classique",
        price=30.0,
        is_available=True
    )
    db_session.add(menu_item)
    await db_session.flush()
    
    mod_group = ModifierGroup(
        menu_item_id=menu_item.id,
        category_id=category.id,
        name_en="Sauce",
        name_ar="صلصة",
        name_fr="Sauce",
        min_selection=1,
        max_selection=2,
        group_type="optional"
    )
    db_session.add(mod_group)
    await db_session.flush()
    
    mod_opt1 = ModifierOption(
        group_id=mod_group.id,
        name_en="Algérienne",
        name_ar="جزائرية",
        name_fr="Algérienne",
        price_override=0.0,
        is_available=True
    )
    mod_opt2 = ModifierOption(
        group_id=mod_group.id,
        name_en="Extra Cheese",
        name_ar="جبن إضافي",
        name_fr="Fromage Extra",
        price_override=5.0,
        is_available=True
    )
    db_session.add_all([mod_opt1, mod_opt2])
    await db_session.commit()
    
    return {
        "category": category,
        "menu_item": menu_item,
        "mod_group": mod_group,
        "mod_opt1": mod_opt1,
        "mod_opt2": mod_opt2
    }

@pytest.fixture()
def auth_tokens(seed_restaurant):
    owner_token = create_access_token(data={"sub": "owner@example.com"})
    
    cashier_token = create_access_token(data={"sub": "cashier@example.com"})
    staff_token = create_access_token(data={"sub": "staff@example.com"})
    admin_token = create_access_token(data={"sub": "admin@example.com"})
    
    return {
        "owner": {"Cookie": f"access_token={owner_token}"},
        "cashier": {"Cookie": f"access_token={cashier_token}"},
        "staff": {"Cookie": f"access_token={staff_token}"},
        "admin": {"Cookie": f"access_token={admin_token}"}
    }

@pytest_asyncio.fixture(autouse=True)
async def mock_whatsapp_service():
    with patch("app.services.whatsapp.WhatsAppService.send_text_message", new_callable=AsyncMock) as mock_send_text, \
         patch("app.services.whatsapp.WhatsAppService.send_magic_link", new_callable=AsyncMock) as mock_send_magic, \
         patch("app.services.whatsapp.WhatsAppService.send_language_picker", new_callable=AsyncMock) as mock_picker, \
         patch("app.services.whatsapp.WhatsAppService._post", new_callable=AsyncMock) as mock_post:
        yield {
            "send_text_message": mock_send_text,
            "send_magic_link": mock_send_magic,
            "send_language_picker": mock_picker,
            "_post": mock_post
        }
