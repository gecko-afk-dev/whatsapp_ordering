"""
Order receipt rendering for WhatsApp message templates.

A WhatsApp template has a FIXED number of {{n}} placeholders and cannot loop
over order items, so the itemised part of the order-confirmation message is
pre-rendered here into ONE plain-text string and passed as a single template
variable ({{2}} of `order_confirmed`). That is a constraint of the WhatsApp
Template API, not a shortcut.

This module is deliberately kept out of app/services/whatsapp.py, which stays a
pure transport layer.
"""
from __future__ import annotations

import logging

from app.models import Order, Restaurant

logger = logging.getLogger(__name__)

# WhatsApp caps a template body at 1024 characters INCLUDING resolved variables.
# The fixed text of `order_confirmed` is ~120 characters, so the receipt itself
# is budgeted at 850 — leaving comfortable headroom under the hard limit.
RECEIPT_MAX_CHARS = 850

# When a receipt busts the budget, show at most this many items before the
# "…and N more" notice.
TRUNCATED_ITEM_COUNT = 6

# GEQO has no customer-facing emailed or printed receipt today — EmailService
# only mails restaurant owners and platform admins, and Customer carries no
# email address at all. So this notice deliberately points at the one channel
# that does exist rather than promising one that does not.
TRUNCATION_NOTICE = "…and {count} more item(s). Contact the restaurant for the full list."


def _money(value) -> str:
    """Format a MAD amount. Always two decimals, never monospace-padded."""
    try:
        return f"{float(value or 0):.2f} MAD"
    except (TypeError, ValueError):
        return "0.00 MAD"


def _item_name(order_item) -> str:
    """
    Resolve an order line's display name.

    These six lifecycle templates no longer branch on `customer.language`, so
    the English name is the canonical one — matching the existing convention in
    OrderService.notify_customer_background.
    """
    menu_item = getattr(order_item, "menu_item", None)
    if menu_item is None:
        return "Item"
    for attr in ("name_en", "name_fr", "name_ar"):
        name = getattr(menu_item, attr, None)
        if name:
            return name
    return "Item"


def _modifier_name(order_item_modifier) -> str:
    option = getattr(order_item_modifier, "modifier_option", None)
    if option is None:
        return ""
    for attr in ("name_en", "name_fr", "name_ar"):
        name = getattr(option, attr, None)
        if name:
            return name
    return ""


def _render_item_block(order_item) -> str:
    """
    One order line plus its modifiers as indented sub-lines.

    `unit_price` already includes any modifier price_override (applied in
    OrderService.process_flow_submission and the PWA checkout path), so the
    line total is simply unit_price × quantity and modifiers are listed for
    information only, without their own prices.
    """
    quantity = getattr(order_item, "quantity", 1) or 1
    unit_price = getattr(order_item, "unit_price", 0.0) or 0.0
    lines = [f"{quantity}x {_item_name(order_item)} - {_money(unit_price * quantity)}"]

    for modifier in getattr(order_item, "modifiers", None) or []:
        name = _modifier_name(modifier)
        if name:
            lines.append(f"   + {name}")

    return "\n".join(lines)


def _assemble(item_blocks, dropped_count: int, order: Order) -> str:
    """Glue the item blocks to the delivery fee / note / total summary block."""
    parts = list(item_blocks)
    if dropped_count > 0:
        parts.append(TRUNCATION_NOTICE.format(count=dropped_count))

    summary = []

    # Omitted entirely at zero — covers both an explicit 0 MAD setting and a GPS
    # pin that landed inside a free-delivery zone. Never print "0.00 MAD".
    delivery_fee = getattr(order, "delivery_fee", 0.0) or 0.0
    if delivery_fee:
        summary.append(f"Delivery Fee: {_money(delivery_fee)}")

    notes = (getattr(order, "customer_notes", None) or "").strip()
    if notes:
        summary.append(f"Note: {notes}")

    total_line = f"Total: {_money(getattr(order, 'total_price', 0.0))}"

    blocks = []
    if parts:
        blocks.append("\n".join(parts))
    if summary:
        blocks.append("\n".join(summary))
    blocks.append(total_line)

    return "\n\n".join(blocks)


def build_order_receipt_text(order: Order, restaurant: Restaurant) -> str:
    """
    Render the itemised receipt block for the `order_confirmed` template.

    `restaurant` is part of the agreed signature and is accepted so callers and
    future per-restaurant receipt rules (currency, tax lines) do not need a
    signature change; the current plain-MAD format does not read from it.

    IMPORTANT: `order.items`, each item's `menu_item`, and each item's
    `modifiers` → `modifier_option` must already be eagerly loaded. Under async
    SQLAlchemy a lazy load from this synchronous function would raise
    MissingGreenlet. See the selectinload chain in the checkout call site.

    The returned string is guaranteed not to exceed RECEIPT_MAX_CHARS, so a
    large order can never blow the 1024-character template body limit and cause
    a failed send.
    """
    items = list(getattr(order, "items", None) or [])
    blocks = [_render_item_block(item) for item in items]

    text = _assemble(blocks, 0, order)
    if len(text) <= RECEIPT_MAX_CHARS:
        return text

    # Over budget: fall back to the first N items plus a remainder notice.
    # Keep shrinking if N items still don't fit (very long names or many
    # modifiers), because a receipt that never fits would fail the send.
    for keep in range(min(TRUNCATED_ITEM_COUNT, len(blocks)), 0, -1):
        candidate = _assemble(blocks[:keep], len(blocks) - keep, order)
        if len(candidate) <= RECEIPT_MAX_CHARS:
            return candidate

    # Last resort: no item fits. Ship the summary block alone rather than a
    # message Meta will reject.
    logger.warning(
        "[receipts] Order %s receipt exceeded %d chars with even one item; "
        "sending summary only.",
        getattr(order, "tracking_code", getattr(order, "id", "?")),
        RECEIPT_MAX_CHARS,
    )
    summary_only = _assemble([], len(blocks), order)
    return summary_only[:RECEIPT_MAX_CHARS]
