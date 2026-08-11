import pytest
import hmac
import hashlib
import json
from app.core.config import settings
from app.models import RestaurantStatus, Customer

def get_webhook_signature(payload: dict) -> str:
    secret = settings.WHATSAPP_APP_SECRET
    raw_body = json.dumps(payload).encode("utf-8")
    expected_signature = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return f"sha256={expected_signature}"

def generate_webhook_payload(wa_id: str = "212600000000") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "fake_phone_id"},
                            "messages": [
                                {
                                    "from": wa_id,
                                    "type": "text",
                                    "text": {"body": "Hello"}
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

@pytest.mark.asyncio
async def test_webhook_verify(async_client):
    response = await async_client.get(
        "/api/v1/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
            "hub.challenge": "1158201444"
        }
    )
    assert response.status_code == 200
    assert response.text == "1158201444"

@pytest.mark.asyncio
async def test_webhook_active_restaurant(async_client, seed_restaurant, mock_whatsapp_service, db_session):
    # Customer doesn't exist, will create and send language picker
    payload = generate_webhook_payload("212600000000")
    signature = get_webhook_signature(payload)
    
    response = await async_client.post(
        "/api/v1/webhook",
        json=payload,
        headers={"X-Hub-Signature-256": signature}
    )
    
    assert response.status_code == 200
    mock_whatsapp_service["send_language_picker"].assert_called_once_with("212600000000")

    # Second message: if language exists, it should generate magic link
    db_session.add(Customer(wa_id="212600000001", language="en"))
    await db_session.commit()
    
    payload2 = generate_webhook_payload("212600000001")
    signature2 = get_webhook_signature(payload2)
    response2 = await async_client.post(
        "/api/v1/webhook",
        json=payload2,
        headers={"X-Hub-Signature-256": signature2}
    )
    assert response2.status_code == 200
    mock_whatsapp_service["send_magic_link"].assert_called_once()

@pytest.mark.asyncio
async def test_webhook_closed_restaurant(async_client, seed_restaurant, mock_whatsapp_service, db_session):
    seed_restaurant.is_accepting_orders = False
    await db_session.commit()
    
    db_session.add(Customer(wa_id="212600000002", language="en"))
    await db_session.commit()

    payload = generate_webhook_payload("212600000002")
    signature = get_webhook_signature(payload)
    
    response = await async_client.post(
        "/api/v1/webhook",
        json=payload,
        headers={"X-Hub-Signature-256": signature}
    )
    assert response.status_code == 200
    mock_whatsapp_service["send_text_message"].assert_called_once()
    called_msg = mock_whatsapp_service["send_text_message"].call_args[0][1]
    assert "currently closed" in called_msg.lower()

@pytest.mark.asyncio
async def test_webhook_negative_balance(async_client, seed_restaurant, mock_whatsapp_service, db_session):
    seed_restaurant.wallet_balance = -76.0
    await db_session.commit()
    
    db_session.add(Customer(wa_id="212600000003", language="en"))
    await db_session.commit()

    payload = generate_webhook_payload("212600000003")
    signature = get_webhook_signature(payload)
    
    response = await async_client.post(
        "/api/v1/webhook",
        json=payload,
        headers={"X-Hub-Signature-256": signature}
    )
    assert response.status_code == 200
    mock_whatsapp_service["send_text_message"].assert_called_once()
    called_msg = mock_whatsapp_service["send_text_message"].call_args[0][1]
    assert "maintenance" in called_msg.lower()
