import pytest
from app.core.auth import create_access_token

def get_auth_headers(wa_id: str, restaurant_id: int):
    token = create_access_token(data={"sub": wa_id, "rid": restaurant_id})
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_checkout_recalculate_price(async_client, seed_restaurant, seed_menu, db_session):
    headers = get_auth_headers("212600000000", seed_restaurant.id)
    payload = {
        "fulfillment_method": "pickup",
        "items": [
            {
                "menu_item_id": seed_menu["menu_item"].id,
                "quantity": 1,
                "exclusions": [],
                "modifiers": [seed_menu["mod_opt2"].id] # Extra Cheese (+5.0)
            }
        ]
    }
    
    response = await async_client.post(
        "/api/v1/public/orders/checkout",
        json=payload,
        headers=headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] is not None
    
    # Check the database for actual total price
    from sqlalchemy.future import select
    from app.models import Order
    order = (await db_session.execute(select(Order).where(Order.id == data["order_id"]))).scalar_one_or_none()
    
    # 30.0 (Burger) + 5.0 (Extra Cheese) = 35.0
    assert order.total_price == 35.0

@pytest.mark.asyncio
async def test_checkout_modifier_bounds(async_client, seed_restaurant, seed_menu):
    headers = get_auth_headers("212600000001", seed_restaurant.id)
    # Violate min_selection (requires at least 1, but we send 0)
    payload = {
        "fulfillment_method": "pickup",
        "items": [
            {
                "menu_item_id": seed_menu["menu_item"].id,
                "quantity": 1,
                "exclusions": [],
                "modifiers": [] # Empty, but min_selection is 1
            }
        ]
    }
    
    response = await async_client.post(
        "/api/v1/public/orders/checkout",
        json=payload,
        headers=headers
    )
    
    assert response.status_code == 400
    assert "modifier" in response.text.lower() or "selection" in response.text.lower()

@pytest.mark.asyncio
async def test_checkout_out_of_stock(async_client, seed_restaurant, seed_menu, db_session):
    # Set item out of stock
    seed_menu["menu_item"].is_available = False
    await db_session.commit()
    
    headers = get_auth_headers("212600000002", seed_restaurant.id)
    payload = {
        "fulfillment_method": "pickup",
        "items": [
            {
                "menu_item_id": seed_menu["menu_item"].id,
                "quantity": 1,
                "exclusions": [],
                "modifiers": [seed_menu["mod_opt1"].id]
            }
        ]
    }
    
    response = await async_client.post(
        "/api/v1/public/orders/checkout",
        json=payload,
        headers=headers
    )
    
    assert response.status_code == 400
    assert "available" in response.text.lower() or "stock" in response.text.lower()

@pytest.mark.asyncio
async def test_checkout_geo_validation_outside(async_client, seed_restaurant, seed_menu):
    headers = get_auth_headers("212600000003", seed_restaurant.id)
    payload = {
        "fulfillment_method": "delivery",
        "latitude": 33.5731,
        "longitude": -7.5898,
        "items": [
            {
                "menu_item_id": seed_menu["menu_item"].id,
                "quantity": 1,
                "exclusions": [],
                "modifiers": [seed_menu["mod_opt1"].id]
            }
        ]
    }
    
    response = await async_client.post(
        "/api/v1/public/orders/checkout",
        json=payload,
        headers=headers
    )
    
    assert response.status_code == 400
    assert "outside" in response.text.lower() or "zone" in response.text.lower() or "radius" in response.text.lower()

@pytest.mark.asyncio
async def test_checkout_atomic_wallet_deduction(async_client, seed_restaurant, seed_menu, db_session):
    initial_balance = seed_restaurant.wallet_balance
    
    headers = get_auth_headers("212600000004", seed_restaurant.id)
    payload = {
        "fulfillment_method": "pickup",
        "items": [
            {
                "menu_item_id": seed_menu["menu_item"].id,
                "quantity": 1,
                "exclusions": [],
                "modifiers": [seed_menu["mod_opt1"].id]
            }
        ]
    }
    
    response = await async_client.post(
        "/api/v1/public/orders/checkout",
        json=payload,
        headers=headers
    )
    
    assert response.status_code == 200
    
    # Check if wallet_balance was deducted by 3.0 MAD
    from sqlalchemy.future import select
    from app.models import Restaurant
    
    updated_restaurant = (await db_session.execute(
        select(Restaurant).where(Restaurant.id == seed_restaurant.id)
    )).scalar_one()
    
    assert updated_restaurant.wallet_balance == initial_balance - 3.0
    
    # Check WalletTransaction
    from sqlalchemy.future import select
    from app.models import WalletTransaction
    tx = (await db_session.execute(
        select(WalletTransaction).where(WalletTransaction.restaurant_id == seed_restaurant.id)
    )).scalars().first()
    
    assert tx is not None
    assert tx.amount == -3.0
