"""
Fixed catalog of GEQO's WhatsApp order-lifecycle message templates.

These six UTILITY-category templates cover the full customer order lifecycle.
Their wording is PLATFORM-OWNED and deliberately NOT editable by restaurant
owners or cashiers.

Why the copy is frozen
----------------------
WhatsApp classifies a template by its rendered content, not merely by the
category it was registered under. If a restaurant could slip promotional copy
into the body of a template registered as UTILITY, the WABA itself risks being
restricted. Every restaurant-specific value that legitimately varies (order
code, driver name, delivery PIN, itemised receipt) is therefore passed as a
positional {{n}} variable that GEQO renders server-side — never as free text.

The {{n}} arity is fixed
------------------------
A WhatsApp template cannot loop over order items. The itemised part of the
confirmation message is pre-rendered server-side into ONE string and sent as a
single variable ({{2}} of `order_confirmed`). See
`app.services.receipts.build_order_receipt_text`. This is intentional.

Each entry is consumed by three call sites:
  * registration  — app/api/admin.py, POST /admin/restaurant/{id}/provision-templates
  * sending       — app/services/whatsapp.py, WhatsAppService.send_template_message
  * preview       — app/api/admin.py, GET /admin/restaurant/message-templates
"""
from __future__ import annotations

from typing import Dict, List

# Meta's Message Template Management API language code. The bodies below are
# intentionally bilingual (English + Moroccan Darija in Arabic script) inside a
# SINGLE template, so only one language variant is registered per template.
# `customer.language` is NOT consulted for these six sends.
TEMPLATE_LANGUAGE = "en"

TEMPLATE_CATEGORY = "UTILITY"


class TemplateKey:
    """Stable internal keys. Also the Meta template names (lowercase + _)."""

    ORDER_CONFIRMED = "order_confirmed"
    ORDER_IN_KITCHEN = "order_in_kitchen"
    ORDER_READY_PICKUP = "order_ready_pickup"
    ORDER_DISPATCHED = "order_dispatched"
    ORDER_DELIVERED = "order_delivered"
    ORDER_CANCELLED = "order_cancelled"


# NOTE: body text is frozen. Do not parameterise, translate, or make any part of
# this dict configurable per restaurant without a WhatsApp policy review first.
ORDER_LIFECYCLE_TEMPLATES: List[Dict] = [
    {
        "key": TemplateKey.ORDER_CONFIRMED,
        # Human-readable label for the read-only dashboard preview page.
        "label": "Order Confirmed",
        "description": "Sent automatically the moment checkout completes.",
        # {{1}} order tracking code, {{2}} pre-rendered receipt block
        "variables": ["order_code", "receipt_block"],
        "body": (
            "✅ *Order Confirmed – تم تأكيد الطلب*\n"
            "Order #{{1}} · توصلنا بالطلب ديالكم، خليكم معانا 🙏\n"
            "\n"
            "{{2}}"
        ),
        "example": [
            "A4F9K2",
            "2x Classic Burger - 70.00 MAD\n   + Extra Cheese\n1x Fries - 20.00 MAD\n\nDelivery Fee: 10.00 MAD\n\nTotal: 100.00 MAD",
        ],
    },
    {
        "key": TemplateKey.ORDER_IN_KITCHEN,
        "label": "In the Kitchen",
        "description": "Sent when the cashier accepts the order.",
        "variables": ["order_code"],
        "body": (
            "👨‍🍳 *Your order #{{1}} is in the kitchen!*\n"
            "الطلب ديالكم وصل للمطبخ 🍳"
        ),
        "example": ["A4F9K2"],
    },
    {
        "key": TemplateKey.ORDER_READY_PICKUP,
        "label": "Ready for Pickup",
        "description": "Sent when a pickup order is marked ready.",
        "variables": ["order_code"],
        "body": (
            "🥡 *Your order #{{1}} is ready for pickup!*\n"
            "طلبكم جاهز، تفضلوا للاستلام من الكونتوار 🙌"
        ),
        "example": ["A4F9K2"],
    },
    {
        "key": TemplateKey.ORDER_DISPATCHED,
        "label": "Dispatched",
        "description": "Sent when a delivery order is dispatched to a driver.",
        # {{1}} order code, {{2}} driver name, {{3}} delivery PIN
        "variables": ["order_code", "driver_name", "delivery_pin"],
        "body": (
            "🛵 *Your order #{{1}} is on its way!* Our delivery agent *{{2}}* is "
            "heading to you. Please share this PIN when they arrive: *{{3}}*\n"
            "الطلب ديالكم فالطريق مع السائق {{2}}، عطيه الرمز السري هادا فاش توصل: *{{3}}*"
        ),
        "example": ["A4F9K2", "Youssef", "482913"],
    },
    {
        "key": TemplateKey.ORDER_DELIVERED,
        "label": "Delivered",
        "description": "Sent after the driver's delivery PIN is verified.",
        "variables": ["order_code"],
        "body": (
            "🍽️ *Order #{{1}} delivered — enjoy your meal!*\n"
            "تم توصيل الطلب، بالصحة والراحة 🙏"
        ),
        "example": ["A4F9K2"],
    },
    {
        "key": TemplateKey.ORDER_CANCELLED,
        "label": "Cancelled",
        "description": "Sent when the cashier rejects the order.",
        "variables": ["order_code"],
        "body": (
            "❌ *Order #{{1}} was cancelled.* Please contact the restaurant with "
            "any questions.\n"
            "تم إلغاء الطلب ديالكم، تواصلو مع المطعم إلا كان عندكم سؤال."
        ),
        "example": ["A4F9K2"],
    },
]

TEMPLATES_BY_KEY: Dict[str, Dict] = {t["key"]: t for t in ORDER_LIFECYCLE_TEMPLATES}

# Ordered keys, matching the customer's journey through the order lifecycle.
TEMPLATE_KEYS: List[str] = [t["key"] for t in ORDER_LIFECYCLE_TEMPLATES]


def build_meta_template_payload(template: Dict) -> Dict:
    """
    Shape one catalog entry into the JSON body Meta's Message Template
    Management API expects at POST /{waba_id}/message_templates.
    """
    body_component: Dict = {"type": "BODY", "text": template["body"]}
    if template.get("example"):
        # Meta requires sample values for every {{n}} in the body.
        body_component["example"] = {"body_text": [template["example"]]}

    return {
        "name": template["key"],
        "language": TEMPLATE_LANGUAGE,
        "category": TEMPLATE_CATEGORY,
        "components": [body_component],
    }
