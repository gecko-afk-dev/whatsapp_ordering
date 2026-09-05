import logging
from typing import Optional
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
import os
import json
import base64
import time
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models import (
    Order, OrderStatus, Driver
)
from app.services.socket_manager import manager
from app.services.whatsapp import WhatsAppService
from app.services.message_templates import TemplateKey
from app.services.event_engine import fire_and_forget_event
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting — driver PIN-verification attempts
# ---------------------------------------------------------------------------
# Mirrors the lightweight in-memory pattern already used as the Redis
# fallback in app/api/webhook.py. Keyed by wa_id (parsed from flow_token,
# below), since that's the identity actually making PIN-guess attempts.
_PIN_ATTEMPT_LOG: dict = {}
PIN_RATE_LIMIT_WINDOW_SECONDS = 60
PIN_RATE_LIMIT_MAX_ATTEMPTS = 5


def _pin_rate_limited(wa_id: str) -> bool:
    """Returns True if this wa_id has exceeded the PIN-attempt rate limit."""
    now = time.time()
    attempts = [
        t for t in _PIN_ATTEMPT_LOG.get(wa_id, [])
        if now - t < PIN_RATE_LIMIT_WINDOW_SECONDS
    ]
    if len(attempts) >= PIN_RATE_LIMIT_MAX_ATTEMPTS:
        _PIN_ATTEMPT_LOG[wa_id] = attempts
        return True
    attempts.append(now)
    _PIN_ATTEMPT_LOG[wa_id] = attempts
    return False


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def load_private_key():
    # 1. Try to load from Render Environment Variable first (Production)
    priv_key_env = os.environ.get("PRIVATE_KEY")
    if priv_key_env:
        # Render sometimes escapes newlines, so we ensure it's formatted correctly
        priv_key_env = priv_key_env.replace("\\n", "\n")
        return serialization.load_pem_private_key(priv_key_env.encode("utf-8"), password=None)

    # 2. Fall back to local file (Local Development)
    private_key_path = "private.pem"
    if not os.path.exists(private_key_path):
        raise FileNotFoundError(f"Private key not found in env var PRIVATE_KEY or file {private_key_path}")
    
    with open(private_key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def decrypt_request(encrypted_aes_key_b64, encrypted_flow_data_b64, initial_vector_b64):
    """Decrypt Meta's encrypted request payload."""
    private_key = load_private_key()

    encrypted_aes_key = base64.b64decode(encrypted_aes_key_b64)
    encrypted_flow_data = base64.b64decode(encrypted_flow_data_b64)
    initial_vector = base64.b64decode(initial_vector_b64)

    aes_key = private_key.decrypt(
        encrypted_aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    encrypted_body = encrypted_flow_data[:-16]
    auth_tag = encrypted_flow_data[-16:]

    cipher = Cipher(algorithms.AES(aes_key), modes.GCM(initial_vector, auth_tag))
    decryptor = cipher.decryptor()
    decrypted_data = decryptor.update(encrypted_body) + decryptor.finalize()
    payload = json.loads(decrypted_data.decode("utf-8"))

    return payload, aes_key, initial_vector

def encrypt_response(response_data, aes_key, initial_vector):
    """Encrypt response payload for Meta (IV must be flipped)."""
    flipped_iv = bytes(b ^ 0xFF for b in initial_vector)
    response_json = json.dumps(response_data).encode("utf-8")

    cipher = Cipher(algorithms.AES(aes_key), modes.GCM(flipped_iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(response_json) + encryptor.finalize()

    return base64.b64encode(encrypted_data + encryptor.tag).decode("utf-8")

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def parse_flow_token(flow_token: str) -> tuple[str, str, Optional[int]]:
    """
    Returns (token_type, wa_id, entity_id). 
    token_type: "session" (customer) or "driver"
    entity_id: restaurant_id (for session) or order_id (for driver)
    """
    if flow_token.startswith("session_"):
        parts = flow_token.rsplit("_", 3)
        if len(parts) == 4:
            try:
                return "session", parts[1], int(parts[2])
            except ValueError:
                pass
    elif flow_token.startswith("driver_"):
        # driver_{order_id}_{to_phone}
        parts = flow_token.split("_", 2)
        if len(parts) == 3:
            try:
                return "driver", parts[2], int(parts[1])
            except ValueError:
                pass
    return "", "", None


# (Consumer Cart logic removed as part of Hybrid PWA Pivot)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.post(
    "/flow-endpoint",
    tags=["Flows"],
    summary="Meta Flow Endpoint",
    description="""
    Handle secure payload exchange and data fetching for WhatsApp Flows.

    Features:
    - **Meta Flow 4-digit driver PIN delivery verification**: Validates the PIN entered by the driver against the generated `delivery_pin` on the order.
    - **`ORDER_DELIVERED` audit logging**: Emits an internal Phase A analytics event when a driver successfully completes a delivery using the PIN.
    """
)
async def flow_data_exchange(request: Request):
    aes_key = None
    initial_vector = None
    payload = {}

    try:
        payload = await request.json()
        is_encrypted = "encrypted_flow_data" in payload

        if is_encrypted:
            logger.info("Received encrypted request from Meta")
            try:
                decrypted_payload, aes_key, initial_vector = decrypt_request(
                    payload["encrypted_aes_key"],
                    payload["encrypted_flow_data"],
                    payload["initial_vector"],
                )
            except Exception as decrypt_err:
                logger.error(
                    "Failed to decrypt Meta request. "
                    "Ensure PRIVATE_KEY env var (production) or private.pem (local) is correctly configured. "
                    "Error: %s",
                    decrypt_err,
                )
                raise
            logger.debug(
                "Decrypted Flow Request: action=%s, screen=%s",
                decrypted_payload.get("action"),
                decrypted_payload.get("screen"),
            )
            response_data = await process_flow_request(decrypted_payload)
            logger.info(f"🚨 Python chose this screen: {response_data}")
            encrypted_response = encrypt_response(response_data, aes_key, initial_vector)
            logger.info("Sending encrypted response to Meta")
            
            # FIX: Return as raw Plain Text, NOT as JSON!
            return PlainTextResponse(content=encrypted_response)

        # Unencrypted requests are only accepted when explicitly enabled for
        # local testing (ALLOW_UNENCRYPTED_FLOW_REQUESTS=true in .env, default
        # false). In any real deployment this path must stay closed — Meta's
        # RSA/AES-GCM encryption is the only thing standing between this
        # endpoint and the driver PIN-verification logic below.
        if not settings.ALLOW_UNENCRYPTED_FLOW_REQUESTS:
            logger.warning(
                "Rejected unencrypted request to /flow-endpoint "
                "(ALLOW_UNENCRYPTED_FLOW_REQUESTS is false)."
            )
            return PlainTextResponse(
                content="Unencrypted requests are not accepted.",
                status_code=403,
            )

        # If not encrypted and explicitly allowed (local testing), return normal JSON
        logger.info(
            "Plain Flow Request: action=%s, screen=%s",
            payload.get("action"),
            payload.get("screen"),
        )
        response_data = await process_flow_request(payload)
        return response_data

    except Exception as e:
        logger.exception("ERROR in flow endpoint")

        error_response = {
            "version": "3.0",
            "screen": "ERROR_SCREEN",
            "data": {"error_message": f"Server error: {str(e)}"},
        }

        # FIX: Ensure errors are also returned as PlainText if the request was encrypted
        if aes_key and initial_vector:
            encrypted_err = encrypt_response(error_response, aes_key, initial_vector)
            return PlainTextResponse(content=encrypted_err)

        return error_response

# ---------------------------------------------------------------------------
# Flow logic
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Flow logic
# ---------------------------------------------------------------------------

async def process_flow_request(payload: dict):
    """Process the flow request payload (decrypted or plain)."""
    action = payload.get("action")
    screen = payload.get("screen")
    data = payload.get("data", {})
    flow_token = payload.get("flow_token", "")

    if action == "ping":
        logger.info("Health check received from Meta")
        return {
            "version": "3.0",
            "data": {"status": "active"},
        }

    token_type, wa_id, entity_id = parse_flow_token(flow_token)

    if not token_type or not wa_id or not entity_id:
        logger.info("No valid flow_token found. Defaulting to Meta Interactive Preview mode.")
        token_type = "session"
        wa_id = "test_user_123"
        entity_id = 4  # FIX: Assign to entity_id so it passes to restaurant_id below!

    async with AsyncSessionLocal() as db:
        
        # --- DRIVER PIN VERIFICATION LOGIC ---
        if token_type == "driver":
            order_id = entity_id
            order_req = await db.execute(select(Order).options(joinedload(Order.restaurant)).where(Order.id == order_id))
            order = order_req.scalar_one_or_none()
            
            if not order:
                return {"version": "3.0", "screen": "ERROR_SCREEN", "data": {"error_message": "Order not found."}}
                
            restaurant = order.restaurant
            wa_service = WhatsAppService(token=restaurant.api_token, phone_id=restaurant.phone_number_id)
            
            if action == "data_exchange" and screen == "CONFIRM_DELIVERY_SCREEN":
                pin_entered = data.get("delivery_pin", "").strip().upper()
                
                if order.status == OrderStatus.DELIVERED:
                    return {"version": "3.0", "screen": "SUCCESS_SCREEN", "data": {"message": "Already delivered!"}}

                if _pin_rate_limited(wa_id):
                    return {
                        "version": "3.0",
                        "screen": "CONFIRM_DELIVERY_SCREEN",
                        "data": {
                            "error_message": "Too many attempts. Please wait a minute and try again.",
                            "order_id": order_id
                        }
                    }

                # Check PIN
                if not order.delivery_pin or order.delivery_pin.upper() != pin_entered:
                    return {
                        "version": "3.0",
                        "screen": "CONFIRM_DELIVERY_SCREEN",
                        "data": {
                            "error_message": "Invalid PIN. Please try again.",
                            "order_id": order_id
                        }
                    }
                
                # Verify Driver
                driver_req = await db.execute(select(Driver).where(Driver.wa_id == wa_id, Driver.is_active))
                driver = driver_req.scalar_one_or_none()
                if not driver or driver.id != order.driver_id:
                    return {"version": "3.0", "screen": "ERROR_SCREEN", "data": {"error_message": "Unauthorized driver."}}
                
                # Success — FIX-7: Write audit log for delivery confirmation
                order.status = OrderStatus.DELIVERED
                
                from app.services.audit import log_audit_action
                await log_audit_action(
                    db=db,
                    actor_user_id=driver.id,  # driver as actor
                    actor_email=f"driver:{driver.wa_id}",
                    action="ORDER_DELIVERED",
                    target=f"order_id={order.id}",
                    detail={
                        "tracking_code": order.tracking_code,
                        "driver_id": driver.id,
                        "driver_name": driver.name,
                        "driver_wa_id": driver.wa_id,
                        "pin_verified": True
                    },
                    restaurant_id=restaurant.id
                )
                
                await db.commit()
                
                # Emit: PIN was verified and delivery marked complete
                fire_and_forget_event(
                    event_type="order.pin_verified",
                    channel="system",
                    restaurant_id=restaurant.id,
                    payload={
                        "order_id": order_id,
                        "driver_id": driver.id,
                        "tracking_code": order.tracking_code,
                    },
                )
                fire_and_forget_event(
                    event_type="order.completed",
                    channel="system",
                    restaurant_id=restaurant.id,
                    payload={
                        "order_id": order_id,
                        "tracking_code": order.tracking_code,
                        "total_price": order.total_price,
                    },
                )
                
                # Notify Dashboard
                await manager.broadcast_to_restaurant(restaurant.id, {"event": "ORDER_STATUS_UPDATED", "order_id": order.id, "new_status": "delivered"})
                
                # Notify Customer — the `order_delivered` UTILITY template
                # replaces BOTH the old status notification and the separate
                # trilingual thank-you text that followed it. The template body
                # is bilingual (EN + Darija) on its own, so customer.language is
                # no longer consulted here.
                await wa_service.send_template_message(
                    order.customer_wa_id,
                    TemplateKey.ORDER_DELIVERED,
                    [order.tracking_code],
                )
                
                # Success screen for driver
                return {
                    "version": "3.0",
                    "screen": "SUCCESS_SCREEN",
                    "data": {"message": "Delivery Confirmed! 🚚"}
                }
                
            # Default for driver flow
            return {
                "version": "3.0",
                "screen": "CONFIRM_DELIVERY_SCREEN",
                "data": {"order_id": order_id, "error_message": ""}
            }
        
        # --- CUSTOMER MENU LOGIC (REMOVED) ---
        # The consumer flow has been replaced by the Hybrid PWA Funnel.
        # Flow logic is now strictly used for Driver PIN delivery confirmations.
            
        return {"version": "3.0", "screen": "SUCCESS_SCREEN", "data": {"message": "Operation completed."}}