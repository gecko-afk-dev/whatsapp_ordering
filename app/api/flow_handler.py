import json
import logging
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import delete
import os
import base64
from fastapi import APIRouter, Request
from app.core.database import AsyncSessionLocal
from app.models import (
    Category, MenuItem, Customer, Restaurant,
    Cart, CartItem, CartItemExclusion, CartItemModifier,
    ModifierGroup, ModifierOption
)
from app.services.order_service import OrderService
from app.services.socket_manager import manager
from app.services.whatsapp import WhatsAppService
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def load_private_key():
    private_key_path = "private.pem"
    if not os.path.exists(private_key_path):
        raise FileNotFoundError(f"Private key not found: {private_key_path}")
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

def parse_flow_token(flow_token: str) -> tuple[str, int | None]:
    """
    Token format: session_{wa_id}_{restaurant_id}_{timestamp}
    Returns (wa_id, restaurant_id). Both are empty/None on parse failure.
    """
    parts = flow_token.rsplit("_", 3)
    if len(parts) != 4 or parts[0] != "session":
        return "", None

    wa_id = parts[1]
    try:
        restaurant_id = int(parts[2])
        return wa_id, restaurant_id
    except ValueError:
        return "", None


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


async def add_item_to_cart(db, cart: Cart, menu_item_id: int, quantity: int, modifier_option_ids: list[int] = None, exclusions: list[str] = None):
    """Add or update an item in the cart with modifiers and exclusions."""
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
            decrypted_payload, aes_key, initial_vector = decrypt_request(
                payload["encrypted_aes_key"],
                payload["encrypted_flow_data"],
                payload["initial_vector"],
            )
            logger.debug(
                "Decrypted Flow Request: action=%s, screen=%s",
                decrypted_payload.get("action"),
                decrypted_payload.get("screen"),
            )
            response_data = await process_flow_request(decrypted_payload)
            encrypted_response = encrypt_response(response_data, aes_key, initial_vector)
            logger.info("Sending encrypted response to Meta")
            return encrypted_response

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

        if aes_key and initial_vector:
            return encrypt_response(error_response, aes_key, initial_vector)

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
        return {"data": {"status": "active"}}

    wa_id, restaurant_id = parse_flow_token(flow_token)

    if not wa_id or not restaurant_id:
        return {
            "version": "3.0",
            "screen": "ERROR_SCREEN",
            "data": {"error_message": "Invalid session token. Please restart."},
        }

    async with AsyncSessionLocal() as db:
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
                select(MenuItem).where(
                    MenuItem.category_id == cat_id,
                    MenuItem.is_available == True,
                ).options(joinedload(MenuItem.modifier_groups).joinedload(ModifierGroup.options))
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

            await add_item_to_cart(db, cart, item_id, qty, modifiers, exclusions)

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
            if data.get("action") == "remove_item":
                item_id = int(data.get("item_id"))
                await db.execute(
                    delete(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id)
                )
                await db.commit()
            elif data.get("action") == "confirm":
                if not cart.items:
                    return {
                        "version": "3.0",
                        "screen": "ERROR_SCREEN",
                        "data": {"error_message": "Your cart is empty. Please add items."},
                    }
                # Send cart summary via WhatsApp
                cart_items, total = await get_cart_summary(db, cart, lang)
                await wa_service.send_cart_summary(wa_id, lang, cart_items, total)
                return {
                    "version": "3.0",
                    "screen": "SUCCESS_SCREEN",
                    "data": {"message": "Order submitted for review."},
                }

        # Default
        return {"version": "3.0", "screen": "SUCCESS_SCREEN", "data": {"message": "Done"}}