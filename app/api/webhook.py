import hashlib
import hmac
import json
import logging
import time
from fastapi import APIRouter, Request, Response
from sqlalchemy.future import select
from sqlalchemy import delete
from app.models import Customer, Restaurant, Order, OrderStatus, FulfillmentMethod, Cart, CartItem
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.services.whatsapp import WhatsAppService
from app.services.socket_manager import manager
from app.services.order_service import OrderService

logger = logging.getLogger(__name__)
router = APIRouter()

# --- In-Memory Rate Limiter ---
USER_RATE_LIMITS = {}
RATE_LIMIT_SECONDS = 1.0
MAX_RATE_LIMIT_ENTRIES = 20000


def verify_webhook_signature(request: Request, raw_body: bytes) -> bool:
    secret = getattr(settings, "WHATSAPP_APP_SECRET", None)
    
    if not secret:
        logger.error("CRITICAL: WHATSAPP_APP_SECRET is not configured! Webhook is rejecting all traffic.")
        return False

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256="):
        logger.warning("Missing or unsupported webhook signature header")
        return False

    expected_signature = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    incoming_signature = signature_header.split("=", 1)[1]
    
    valid = hmac.compare_digest(expected_signature, incoming_signature)
    if not valid:
        logger.warning("Invalid webhook signature. Possible spoofing attack.")
    return valid


@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=str(challenge), media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


async def get_latest_pending_order(db, wa_id: str):
    q = await db.execute(
        select(Order)
        .where(Order.customer_wa_id == wa_id, Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at.desc())
    )
    return q.scalar_one_or_none()


async def get_cart(db, wa_id: str, restaurant_id: int):
    q = await db.execute(
        select(Cart).where(Cart.customer_wa_id == wa_id, Cart.restaurant_id == restaurant_id)
    )
    return q.scalar_one_or_none()


@router.post("/webhook")
async def handle_events(request: Request):
    raw_body = await request.body()
    if not verify_webhook_signature(request, raw_body):
        return Response(content="Verification failed", status_code=403)

    try:
        payload = json.loads(raw_body)

        if not payload.get("entry"):
            return Response(status_code=200)

        value = payload["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return Response(status_code=200)

        phone_id = value["metadata"]["phone_number_id"]
        message = value["messages"][0]
        wa_id = message["from"]

        # --- RATE LIMITING ---
        now = time.time()
        last_request_time = USER_RATE_LIMITS.get(wa_id, 0)
        
        if now - last_request_time < RATE_LIMIT_SECONDS:
            logger.warning(f"Rate limit exceeded for {wa_id}. Dropping message.")
            return Response(status_code=200)
            
        USER_RATE_LIMITS[wa_id] = now
        
        if len(USER_RATE_LIMITS) > MAX_RATE_LIMIT_ENTRIES:
            USER_RATE_LIMITS.clear()
        # ---------------------

        async with AsyncSessionLocal() as db:
            res_query = await db.execute(
                select(Restaurant).where(Restaurant.phone_number_id == phone_id)
            )
            restaurant = res_query.scalar_one_or_none()
            if not restaurant:
                logger.warning("Webhook received for unknown phone_number_id=%s", phone_id)
                return Response(status_code=200)

            wa_service = WhatsAppService(
                token=restaurant.api_token,
                phone_id=restaurant.phone_number_id
            )

            cust_query = await db.execute(
                select(Customer).where(Customer.wa_id == wa_id)
            )
            customer = cust_query.scalar_one_or_none()

            # New customer: create and send language picker
            if not customer:
                customer = Customer(wa_id=wa_id, language=None)
                db.add(customer)
                await db.commit()
                await wa_service.send_language_picker(wa_id)
                return Response(status_code=200)

            # Customer exists but no language selected yet
            if customer.language is None:
                if (
                    message.get("type") == "interactive"
                    and message["interactive"]["type"] == "list_reply"
                ):
                    sel_id = message["interactive"]["list_reply"]["id"]
                    
                    if sel_id.startswith("disp_"):
                        # Manager dispatching to driver
                        _, order_id_str, driver_id_str = sel_id.split("_")
                        order_id = int(order_id_str)
                        driver_id = int(driver_id_str)
                        
                        order = await db.execute(select(Order).where(Order.id == order_id))
                        order = order.scalar_one_or_none()
                        if order:
                            from app.models import Driver
                            driver = await db.execute(select(Driver).where(Driver.id == driver_id))
                            driver = driver.scalar_one_or_none()
                            
                            if driver:
                                order.driver_id = driver.id
                                order.status = OrderStatus.DISPATCHED
                                await db.commit()
                                
                                # Notify customer
                                cust_lang = (await db.execute(select(Customer.language).where(Customer.wa_id == order.customer_wa_id))).scalar_one_or_none() or "fr"
                                await wa_service.send_order_status_notification(order.customer_wa_id, cust_lang, order.id, "dispatched")
                                
                                # Notify driver
                                await wa_service._post({
                                    "messaging_product": "whatsapp",
                                    "to": driver.wa_id,
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button",
                                        "body": {"text": f"🚚 *New Delivery Assignment!*\n\n*Order ID:* #{order.id}\n*Total to Collect:* {order.total_price} MAD (COD)\n*Location:* https://maps.google.com/?q={order.latitude},{order.longitude}\n\nPlease deliver this order and click the button below when done."},
                                        "action": {
                                            "buttons": [
                                                {"type": "reply", "reply": {"id": f"drv_delivered_{order.id}", "title": "Mark Delivered"}}
                                            ]
                                        }
                                    }
                                })
                                
                                # Acknowledge manager
                                await wa_service.send_text_message(wa_id, f"Order #{order.id} dispatched to {driver.name}.")
                        return Response(status_code=200)

                    customer.language = (
                        "ar" if "ar" in sel_id else "fr" if "fr" in sel_id else "en"
                    )
                    await db.commit()
                    await wa_service.send_main_menu_flow(wa_id, customer.language, restaurant.id)
                else:
                    await wa_service.send_language_picker(wa_id)
                return Response(status_code=200)

            # Customer exists with language set
            m_type = message.get("type")

            if m_type == "text":
                await wa_service.send_main_menu_flow(wa_id, customer.language, restaurant.id)
                return Response(status_code=200)

            elif m_type == "interactive":
                i_type = message["interactive"]["type"]

                if i_type == "nfm_reply":
                    order = await get_latest_pending_order(db, wa_id)
                    if order:
                        if order.fulfillment_method == FulfillmentMethod.DELIVERY:
                            await wa_service.request_location(
                                wa_id, customer.language, order.total_price
                            )
                        else:
                            order.status = OrderStatus.RECEIVED
                            await db.commit()
                            await manager.broadcast_to_restaurant(
                                restaurant.id,
                                {"event": "NEW_ORDER", "order_id": order.id},
                            )
                            await wa_service.send_order_confirmation(
                                wa_id, customer.language
                            )
                            await wa_service.notify_manager_new_order(
                                restaurant.owner_wa_id, order.id, order.total_price, order.fulfillment_method.value
                            )
                    return Response(status_code=200)

                elif i_type == "button_reply":
                    btn_id = message["interactive"]["button_reply"]["id"]

                    if btn_id == "confirm_order":
                        cart = await get_cart(db, wa_id, restaurant.id)
                        if cart and cart.items:
                            pending_order = await get_latest_pending_order(db, wa_id)
                            fulfillment_method = (
                                pending_order.fulfillment_method.value
                                if pending_order
                                else "delivery"
                            )

                            order_data = {
                                "method": fulfillment_method,
                                "selected_items": [
                                    {
                                        "id": str(item.menu_item_id),
                                        "qty": item.quantity,
                                        "exclusions": [
                                            exc.ingredient_name for exc in item.exclusions
                                        ],
                                        "modifiers": [
                                            mod.modifier_option_id for mod in item.modifiers
                                        ]
                                    }
                                    for item in cart.items
                                ],
                            }
                            order = await OrderService.process_flow_submission(
                                db, wa_id, restaurant.id, order_data
                            )
                            await db.execute(
                                delete(CartItem).where(CartItem.cart_id == cart.id)
                            )
                            await db.execute(
                                delete(Cart).where(Cart.id == cart.id)
                            )
                            await db.commit()
                            await wa_service.send_order_confirmation(wa_id, customer.language)
                        else:
                            await wa_service.send_text_message(wa_id, "Your cart is empty.")
                        return Response(status_code=200)

                    elif btn_id == "change_order":
                        await wa_service.send_main_menu_flow(wa_id, customer.language, restaurant.id)
                        return Response(status_code=200)

                    elif btn_id.startswith("mgr_accept_"):
                        order_id = int(btn_id.split("_")[2])
                        order = await db.execute(select(Order).where(Order.id == order_id))
                        order = order.scalar_one_or_none()
                        if order:
                            order.status = OrderStatus.PREPARING
                            await db.commit()
                            cust_lang = (await db.execute(select(Customer.language).where(Customer.wa_id == order.customer_wa_id))).scalar_one_or_none() or "fr"
                            await wa_service.send_order_status_notification(order.customer_wa_id, cust_lang, order.id, "preparing")
                            
                            # Give manager next step
                            if order.fulfillment_method == FulfillmentMethod.DELIVERY:
                                await wa_service._post({
                                    "messaging_product": "whatsapp",
                                    "to": wa_id,
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button",
                                        "body": {"text": f"Order #{order_id} is now PREPARING.\nClick Dispatch when it's ready for delivery."},
                                        "action": {
                                            "buttons": [
                                                {"type": "reply", "reply": {"id": f"mgr_dispatch_{order_id}", "title": "Dispatch to Driver"}}
                                            ]
                                        }
                                    }
                                })
                            else:
                                await wa_service._post({
                                    "messaging_product": "whatsapp",
                                    "to": wa_id,
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button",
                                        "body": {"text": f"Order #{order_id} is now PREPARING.\nClick Ready when customer can pick it up."},
                                        "action": {
                                            "buttons": [
                                                {"type": "reply", "reply": {"id": f"mgr_ready_{order_id}", "title": "Ready for Pickup"}}
                                            ]
                                        }
                                    }
                                })
                        return Response(status_code=200)

                    elif btn_id.startswith("mgr_reject_"):
                        order_id = int(btn_id.split("_")[2])
                        order = await db.execute(select(Order).where(Order.id == order_id))
                        order = order.scalar_one_or_none()
                        if order:
                            order.status = OrderStatus.CANCELLED
                            await db.commit()
                            cust_lang = (await db.execute(select(Customer.language).where(Customer.wa_id == order.customer_wa_id))).scalar_one_or_none() or "fr"
                            await wa_service.send_order_status_notification(order.customer_wa_id, cust_lang, order.id, "cancelled")
                            await wa_service.send_text_message(wa_id, f"Order #{order_id} has been rejected.")
                        return Response(status_code=200)

                    elif btn_id.startswith("mgr_ready_"):
                        order_id = int(btn_id.split("_")[2])
                        order = await db.execute(select(Order).where(Order.id == order_id))
                        order = order.scalar_one_or_none()
                        if order:
                            order.status = OrderStatus.READY
                            await db.commit()
                            cust_lang = (await db.execute(select(Customer.language).where(Customer.wa_id == order.customer_wa_id))).scalar_one_or_none() or "fr"
                            await wa_service.send_order_status_notification(order.customer_wa_id, cust_lang, order.id, "ready")
                            await wa_service.send_text_message(wa_id, f"Order #{order_id} marked as Ready.")
                        return Response(status_code=200)

                    elif btn_id.startswith("mgr_dispatch_"):
                        order_id = int(btn_id.split("_")[2])
                        from app.models import Driver
                        drivers_req = await db.execute(select(Driver).where(Driver.restaurant_id == restaurant.id, Driver.is_active == True))
                        drivers = drivers_req.scalars().all()
                        
                        if not drivers:
                            await wa_service.send_text_message(wa_id, "No active drivers available to dispatch.")
                            return Response(status_code=200)
                        
                        rows = [{"id": f"disp_{order_id}_{d.id}", "title": d.name} for d in drivers[:10]]
                        await wa_service._post({
                            "messaging_product": "whatsapp",
                            "recipient_type": "individual",
                            "to": wa_id,
                            "type": "interactive",
                            "interactive": {
                                "type": "list",
                                "header": {"type": "text", "text": f"Dispatch Order #{order_id}"},
                                "body": {"text": "Select a driver:"},
                                "action": {
                                    "button": "Drivers",
                                    "sections": [{"title": "Available Drivers", "rows": rows}]
                                }
                            }
                        })
                        return Response(status_code=200)

                    elif btn_id.startswith("drv_delivered_"):
                        order_id = int(btn_id.split("_")[2])
                        order = await db.execute(select(Order).where(Order.id == order_id))
                        order = order.scalar_one_or_none()
                        if order:
                            order.status = OrderStatus.DELIVERED
                            await db.commit()
                            
                            cust_lang = (await db.execute(select(Customer.language).where(Customer.wa_id == order.customer_wa_id))).scalar_one_or_none() or "fr"
                            await wa_service.send_order_status_notification(order.customer_wa_id, cust_lang, order.id, "delivered")
                            await wa_service.send_text_message(wa_id, f"✅ Order #{order.id} marked as Delivered! Great job.")
                            
                            # Notify manager
                            await wa_service.send_text_message(restaurant.owner_wa_id, f"✅ Order #{order.id} has been delivered by the driver.")
                        return Response(status_code=200)

                    else:
                        await wa_service.send_main_menu_flow(wa_id, customer.language, restaurant.id)
                        return Response(status_code=200)

            elif m_type == "location":
                lat = message["location"]["latitude"]
                lon = message["location"]["longitude"]
                order = await get_latest_pending_order(db, wa_id)
                if order:
                    order.latitude = lat
                    order.longitude = lon
                    order.status = OrderStatus.RECEIVED
                    await db.commit()
                    await manager.broadcast_to_restaurant(
                        restaurant.id,
                        {"event": "NEW_ORDER", "order_id": order.id},
                    )
                    await wa_service.send_order_confirmation(wa_id, customer.language)
                    await wa_service.notify_manager_new_order(
                        restaurant.owner_wa_id, order.id, order.total_price, order.fulfillment_method.value
                    )
                return Response(status_code=200)

            # Fallback for unhandled message types
            await wa_service.send_main_menu_flow(wa_id, customer.language, restaurant.id)
            return Response(status_code=200)

    except json.JSONDecodeError:
        logger.exception("Invalid JSON received by webhook")
        return Response(status_code=400)
    except Exception:
        logger.exception("Unexpected webhook error")
        return Response(status_code=500)