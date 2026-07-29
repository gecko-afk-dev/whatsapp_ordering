import logging
from typing import Optional
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import delete
import os
import json
import base64
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from app.core.database import AsyncSessionLocal
from app.models import (
    Category, MenuItem, Customer, Restaurant,
    Cart, CartItem, CartItemExclusion, CartItemModifier,
    ModifierGroup, Order, OrderStatus, Driver
)
from app.services.socket_manager import manager
from app.services.whatsapp import WhatsAppService
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


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


async def get_or_create_cart(db, wa_id: str, restaurant_id: int):
    """Get or create a cart for the customer."""
    cart_query = await db.execute(
        select(Cart).where(Cart.customer_wa_id == wa_id, Cart.restaurant_id == restaurant_id)
    )
    cart = cart_query.scalar_one_or_none()
    if not cart:
        cart = Cart(customer_wa_id=wa_id, restaurant_id=restaurant_id)
        db.add(cart)
        await db.flush()
    return cart


async def add_item_to_cart(db, cart: Cart, restaurant_id: int, menu_item_id: int, quantity: int, modifier_option_ids: list[int] = None, exclusions: list[str] = None):
    """Add or update an item in the cart with modifiers and exclusions, validating restaurant ownership."""
    item_query = await db.execute(
        select(MenuItem)
        .join(Category)
        .where(MenuItem.id == menu_item_id, Category.restaurant_id == restaurant_id)
    )
    menu_item = item_query.scalar_one_or_none()
    if not menu_item or not menu_item.is_available:
        raise ValueError("Menu item is not available for this restaurant.")

    # Check if item already in cart
    item_query = await db.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.menu_item_id == menu_item_id)
    )
    cart_item = item_query.scalar_one_or_none()

    if cart_item:
        cart_item.quantity += quantity
    else:
        cart_item = CartItem(cart_id=cart.id, menu_item_id=menu_item_id, quantity=quantity)
        db.add(cart_item)
        await db.flush()

    # Handle modifiers attached to this cart item
    if modifier_option_ids:
        for mod_id in modifier_option_ids:
            mod = await db.execute(
                select(ModifierOption)
                .join(ModifierOption.group)
                .join(ModifierGroup.menu_item)
                .join(MenuItem.category)
                .where(ModifierOption.id == mod_id, Category.restaurant_id == restaurant_id)
            )
            mod_option = mod.scalar_one_or_none()
            if not mod_option:
                raise ValueError(f"Modifier option {mod_id} is invalid for this restaurant.")
            db.add(CartItemModifier(cart_item_id=cart_item.id, modifier_option_id=mod_id))

    # Handle exclusions
    if exclusions:
        for exc in exclusions:
            exclusion = CartItemExclusion(cart_item_id=cart_item.id, ingredient_name=exc)
            db.add(exclusion)

    await db.commit()

    # Handle modifiers
    if modifier_option_ids:
        for mod_id in modifier_option_ids:
            mod = CartItemModifier(cart_item_id=cart_item.id, modifier_option_id=mod_id)
            db.add(mod)

    # Handle exclusions
    if exclusions:
        for exc in exclusions:
            exclusion = CartItemExclusion(cart_item_id=cart_item.id, ingredient_name=exc)
            db.add(exclusion)

    await db.commit()


async def get_cart_summary(db, cart: Cart, lang: str):
    """Get cart items with totals."""
    items_query = await db.execute(
        select(CartItem)
        .options(
            joinedload(CartItem.menu_item),
            joinedload(CartItem.modifiers).joinedload(CartItemModifier.modifier_option)
        )
        .where(CartItem.cart_id == cart.id)
    )
    items = items_query.scalars().unique().all()

    total = 0.0
    cart_items = []
    for item in items:
        name = getattr(item.menu_item, f"name_{lang}")
        price = item.menu_item.price
        subtotal = price * item.quantity
        total += subtotal

        mods = [getattr(mod.modifier_option, f"name_{lang}") for mod in item.modifiers]
        cart_items.append({
            "id": str(item.id),
            "name": name,
            "quantity": item.quantity,
            "modifiers": mods,
            "subtotal": f"{subtotal} MAD"
        })

    return cart_items, f"{total} MAD"


async def get_cart_data(db, cart: Cart, lang: str):
    """Get data for cart screen."""
    cart_items, total = await get_cart_summary(db, cart, lang)
    return {
        "cart_items": cart_items,
        "total": total,
        "actions": [
            {"id": "continue_shopping", "title": "Continue Shopping"},
            {"id": "confirm_order", "title": "Confirm Order"},
        ]
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.post("/flow-endpoint")
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
            encrypted_response = encrypt_response(response_data, aes_key, initial_vector)
            logger.info("Sending encrypted response to Meta")
            
            # FIX: Return as raw Plain Text, NOT as JSON!
            return PlainTextResponse(content=encrypted_response)

        # If not encrypted (local testing), return normal JSON
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

async def process_flow_request(payload: dict):
    """Process the flow request payload (decrypted or plain)."""
    action = payload.get("action")
    screen = payload.get("screen")
    data = payload.get("data", {})
    flow_token = payload.get("flow_token", "")

    if action == "ping":
        logger.info("Health check received from Meta")
        return {
            "version": payload.get("version", "3.0"),
            "data": {"status": "active"},
        }

    token_type, wa_id, entity_id = parse_flow_token(flow_token)

    if not token_type or not wa_id or not entity_id:
        return {
            "version": "3.0",
            "screen": "ERROR_SCREEN",
            "data": {"error_message": "Invalid session token. Please restart."},
        }

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
                
                # Success
                order.status = OrderStatus.DELIVERED
                await db.commit()
                
                # Notify Dashboard
                await manager.broadcast_to_restaurant(restaurant.id, {"event": "ORDER_STATUS_UPDATED", "order_id": order.id, "new_status": "delivered"})
                
                # Notify Customer
                cust_req = await db.execute(select(Customer.language).where(Customer.wa_id == order.customer_wa_id))
                cust_lang = cust_req.scalar_one_or_none() or "fr"
                await wa_service.send_order_status_notification(order.customer_wa_id, cust_lang, order.id, "delivered")
                
                # Thank you message to customer
                thank_you_map = {
                    "fr": f"🙏 Merci pour votre commande #{order.id} ! À très bientôt.",
                    "ar": f"🙏 شكراً لطلبك رقم {order.id}! نراكم قريباً.",
                    "en": f"🙏 Thank you for your order #{order.id}! See you soon."
                }
                await wa_service.send_text_message(order.customer_wa_id, thank_you_map[cust_lang])
                
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
        
        # --- CUSTOMER MENU LOGIC ---
        restaurant_id = entity_id
        # Get restaurant for API token
        rest_res = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
        restaurant = rest_res.scalar_one_or_none()
        if not restaurant:
            return {
                "version": "3.0",
                "screen": "ERROR_SCREEN",
                "data": {"error_message": "Restaurant not found."},
            }

        # Create WhatsApp service with restaurant's token
        wa_service = WhatsAppService(token=restaurant.api_token, phone_id=restaurant.phone_number_id)

        cust_res = await db.execute(select(Customer).where(Customer.wa_id == wa_id))
        customer = cust_res.scalar_one_or_none()
        lang = customer.language if customer and customer.language else "fr"

        cart = await get_or_create_cart(db, wa_id, restaurant_id)

        if action == "INIT" or screen == "CATEGORIES_SCREEN":
            cat_query = await db.execute(
                select(Category).where(Category.restaurant_id == restaurant_id)
            )
            categories = cat_query.scalars().all()
            return {
                "version": "3.0",
                "screen": "CATEGORIES_SCREEN",
                "data": {
                    "categories": [
                        {"id": str(c.id), "title": getattr(c, f"name_{lang}")}
                        for c in categories
                    ]
                },
            }

        if action == "data_exchange" and screen == "CATEGORIES_SCREEN":
            cat_id = int(data.get("category_id", 0))
            item_query = await db.execute(
                select(MenuItem)
                .join(Category)
                .where(
                    MenuItem.category_id == cat_id,
                    Category.restaurant_id == restaurant_id,
                    MenuItem.is_available,
                )
                .options(joinedload(MenuItem.modifier_groups).joinedload(ModifierGroup.options))
            )
            items = item_query.scalars().all()
            return {
                "version": "3.0",
                "screen": "ITEMS_SCREEN",
                "data": {
                    "items": [
                        {
                            "id": str(i.id),
                            "title": getattr(i, f"name_{lang}"),
                            "price": f"{i.price} MAD",
                            "item_details": i.item_details if i.item_details else "",
                            "allows_exclusions": i.allows_exclusions,
                            "modifiers": [
                                {
                                    "id": str(g.id),
                                    "title": getattr(g, f"name_{lang}"),
                                    "min": g.min_selection,
                                    "max": g.max_selection,
                                    "options": [
                                        {"id": str(o.id), "title": getattr(o, f"name_{lang}") + (f" (+{o.price_override} MAD)" if o.price_override > 0 else "")}
                                        for o in g.options
                                    ]
                                }
                                for g in i.modifier_groups
                            ]
                        }
                        for i in items
                    ],
                    "fulfillment_options": [
                        {"id": "delivery", "title": "Delivery 🛵"},
                        {"id": "pickup", "title": "Pickup 🥡"},
                    ],
                },
            }

        if action == "data_exchange" and screen == "ITEMS_SCREEN":
            item_id = int(data.get("item_id", 0))
            qty = int(data.get("quantity", 1))
            exclusions = data.get("exclusions", [])
            modifiers = data.get("modifiers", []) # Expecting list of option IDs

            await add_item_to_cart(db, cart, restaurant_id, item_id, qty, modifiers, exclusions)

            return {
                "version": "3.0",
                "screen": "CART_SCREEN",
                "data": await get_cart_data(db, cart, lang),
            }

        if screen == "CART_SCREEN" and action != "data_exchange":
            cart_items, total = await get_cart_summary(db, cart, lang)
            return {
                "version": "3.0",
                "screen": "CART_SCREEN",
                "data": {
                    "cart_items": cart_items,
                    "total": total,
                },
            }

        if action == "data_exchange" and screen == "CART_SCREEN":
            cart_action = data.get("action", "")

            # ── Remove single item from cart ──────────────────────────────
            if cart_action == "remove_item":
                item_id = int(data.get("item_id", 0))
                if item_id:
                    await db.execute(
                        delete(CartItem).where(
                            CartItem.id == item_id,
                            CartItem.cart_id == cart.id  # ensure ownership
                        )
                    )
                    await db.commit()
                # Return updated cart state
                cart_items, total = await get_cart_summary(db, cart, lang)
                return {
                    "version": "3.0",
                    "screen": "CART_SCREEN",
                    "data": await get_cart_data(db, cart, lang),
                }

            # ── Loop-back: "Modifier" — go back to categories, cart intact ──
            # Heuristic: tapping Modifier/Continue Shopping reloads the menu
            # screen while preserving all existing cart items.
            if cart_action in ("continue_shopping", "modify"):
                # Refresh language from DB to ensure preference is current
                fresh_lang_row = await db.execute(
                    select(Customer.language).where(Customer.wa_id == wa_id)
                )
                lang = fresh_lang_row.scalar_one_or_none() or lang

                cat_query = await db.execute(
                    select(Category).where(Category.restaurant_id == restaurant_id)
                )
                categories = cat_query.scalars().all()
                return {
                    "version": "3.0",
                    "screen": "CATEGORIES_SCREEN",
                    "data": {
                        "categories": [
                            {"id": str(c.id), "title": getattr(c, f"name_{lang}")}
                            for c in categories
                        ]
                    },
                }

            # ── Confirm order — empty cart guard ─────────────────────────
            if cart_action == "confirm":
                # Re-load cart items to get accurate count (avoid race condition)
                cart_check = await db.execute(
                    select(CartItem).where(CartItem.cart_id == cart.id)
                )
                cart_item_rows = cart_check.scalars().all()

                if not cart_item_rows:
                    # Fail closed: do not close the Flow if cart is empty
                    return {
                        "version": "3.0",
                        "screen": "CART_SCREEN",
                        "data": {
                            "cart_items": [],
                            "total": "0 MAD",
                            "error": "Votre panier est vide. Ajoutez des articles d'abord."
                            if lang == "fr" else
                            "سلة الطلبات فارغة. أضف عناصر أولاً."
                            if lang == "ar" else
                            "Your cart is empty. Please add items first.",
                        },
                    }

                # Cart has items — send WhatsApp summary and close Flow
                cart_items, total = await get_cart_summary(db, cart, lang)
                await wa_service.send_cart_summary(wa_id, lang, cart_items, total)
                return {
                    "version": "3.0",
                    "screen": "SUCCESS_SCREEN",
                    "data": {
                        "message": "Commande envoyée! Partagez votre position."
                        if lang == "fr" else
                        "تم إرسال طلبك! شارك موقعك."
                        if lang == "ar" else
                        "Order sent! Please share your location."
                    },
                }

        # Default fallback — return current cart state if possible
        if cart:
            return {
                "version": "3.0",
                "screen": "CART_SCREEN",
                "data": await get_cart_data(db, cart, lang),
            }
        return {"version": "3.0", "screen": "SUCCESS_SCREEN", "data": {"message": "Done"}}