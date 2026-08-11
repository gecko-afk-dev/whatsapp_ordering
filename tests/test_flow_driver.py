import pytest
from app.models import OrderStatus

@pytest.mark.asyncio
async def test_driver_pin_flow_valid(async_client, seed_restaurant, db_session):
    # Setup driver
    from app.models import Driver
    driver = Driver(
        restaurant_id=seed_restaurant.id,
        name="Test Driver",
        wa_id="212600000001",
        is_active=True
    )
    db_session.add(driver)
    await db_session.flush()

    # Setup an order with a PIN
    from app.models import Order, FulfillmentMethod
    order = Order(
        restaurant_id=seed_restaurant.id,
        customer_wa_id="212600000000",
        fulfillment_method=FulfillmentMethod.DELIVERY,
        status=OrderStatus.DISPATCHED,
        total_price=35.0,
        delivery_pin="123456",
        driver_id=driver.id
    )
    db_session.add(order)
    await db_session.commit()
    
    payload = {
        "action": "data_exchange",
        "screen": "CONFIRM_DELIVERY_SCREEN",
        "flow_token": f"driver_{order.id}_{driver.wa_id}",
        "data": {
            "delivery_pin": "123456"
        }
    }
    
    response = await async_client.post(
        "/api/v1/flow/flow-endpoint",
        json=payload
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["screen"] == "SUCCESS_SCREEN"
    
    # Assert order status
    from sqlalchemy.future import select
    from app.models import Order
    updated_order = (await db_session.execute(
        select(Order).where(Order.id == order.id)
    )).scalar_one()
    
    assert updated_order.status == OrderStatus.DELIVERED
    
    # Assert AuditLog
    from app.models import AuditLog
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.target == f"order_id={order.id}"))).scalars().first()
    
    assert audit is not None
    assert audit.action == "ORDER_DELIVERED"
