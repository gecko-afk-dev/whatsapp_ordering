"""
Unit tests for app.services.receipts.build_order_receipt_text.

These build transient (unpersisted) ORM instances rather than hitting the
database: the receipt builder is a pure synchronous function over already-loaded
relationships, so no session is needed and the tests stay fast and DB-agnostic.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import re

import pytest

from app.models import (
    FulfillmentMethod,
    MenuItem,
    ModifierOption,
    Order,
    OrderItem,
    OrderItemModifier,
    OrderStatus,
    Restaurant,
)
from app.services.receipts import (
    RECEIPT_MAX_CHARS,
    build_order_receipt_text,
)


def _menu_item(name_en, price, name_fr=None, name_ar=None):
    return MenuItem(
        name_en=name_en,
        name_fr=name_fr or name_en,
        name_ar=name_ar or name_en,
        price=price,
        is_available=True,
    )


def _order_item(menu_item, quantity=1, unit_price=None, modifier_names=()):
    """unit_price already includes modifier price_overrides (see OrderService)."""
    line = OrderItem(
        menu_item=menu_item,
        quantity=quantity,
        unit_price=menu_item.price if unit_price is None else unit_price,
    )
    line.modifiers = [
        OrderItemModifier(
            modifier_option=ModifierOption(
                name_en=name, name_fr=name, name_ar=name, price_override=0.0
            )
        )
        for name in modifier_names
    ]
    return line


def _order(items, total_price, delivery_fee=0.0, customer_notes=None,
           method=FulfillmentMethod.DELIVERY):
    order = Order(
        tracking_code="A4F9K2",
        customer_wa_id="212600000000",
        fulfillment_method=method,
        status=OrderStatus.PENDING,
        total_price=total_price,
        delivery_fee=delivery_fee,
        customer_notes=customer_notes,
    )
    order.items = items
    return order


@pytest.fixture()
def restaurant():
    return Restaurant(
        name="Test Restaurant",
        wa_phone_number="123456789",
        api_token="fake_token",
        phone_number_id="fake_phone_id",
        owner_wa_id="987654321",
    )


# ── Normal order ──────────────────────────────────────────────────────────

def test_normal_order_renders_items_fee_and_total(restaurant):
    order = _order(
        items=[
            _order_item(_menu_item("Classic Burger", 35.0), quantity=2),
            _order_item(_menu_item("Fries", 20.0), quantity=1),
        ],
        total_price=100.0,
        delivery_fee=10.0,
    )

    text = build_order_receipt_text(order, restaurant)

    assert text == (
        "2x Classic Burger - 70.00 MAD\n"
        "1x Fries - 20.00 MAD\n"
        "\n"
        "Delivery Fee: 10.00 MAD\n"
        "\n"
        "Total: 100.00 MAD"
    )


def test_line_total_is_unit_price_times_quantity(restaurant):
    order = _order(
        items=[_order_item(_menu_item("Tagine", 45.5), quantity=3)],
        total_price=136.5,
    )
    assert "3x Tagine - 136.50 MAD" in build_order_receipt_text(order, restaurant)


# ── Zero delivery fee ─────────────────────────────────────────────────────

def test_zero_delivery_fee_line_is_omitted_entirely(restaurant):
    order = _order(
        items=[_order_item(_menu_item("Fries", 20.0))],
        total_price=20.0,
        delivery_fee=0.0,
    )

    text = build_order_receipt_text(order, restaurant)

    assert "Delivery Fee" not in text
    # No zero-valued money line anywhere (a bare "0.00 MAD" on its own line).
    assert not re.search(r"^\S.*: 0\.00 MAD$", text, re.MULTILINE)
    assert text == "1x Fries - 20.00 MAD\n\nTotal: 20.00 MAD"


def test_free_zone_delivery_fee_override_omits_the_line(restaurant):
    """A delivery order whose GPS pin fell inside a free-delivery zone."""
    order = _order(
        items=[_order_item(_menu_item("Pizza", 60.0))],
        total_price=60.0,
        delivery_fee=0.0,
        method=FulfillmentMethod.DELIVERY,
    )

    text = build_order_receipt_text(order, restaurant)

    assert "Delivery Fee" not in text
    assert text.endswith("Total: 60.00 MAD")


# ── Customer notes ────────────────────────────────────────────────────────

def test_customer_notes_render_before_the_total(restaurant):
    order = _order(
        items=[_order_item(_menu_item("Pizza", 60.0))],
        total_price=70.0,
        delivery_fee=10.0,
        customer_notes="Ring the bell twice",
    )

    text = build_order_receipt_text(order, restaurant)

    assert "Note: Ring the bell twice" in text
    assert text.index("Note:") < text.index("Total:")
    assert text.index("Delivery Fee:") < text.index("Note:")


def test_blank_customer_notes_render_no_note_line(restaurant):
    order = _order(
        items=[_order_item(_menu_item("Pizza", 60.0))],
        total_price=60.0,
        customer_notes="   ",
    )
    assert "Note:" not in build_order_receipt_text(order, restaurant)


# ── Modifiers ─────────────────────────────────────────────────────────────

def test_modifiers_render_as_indented_sublines_under_their_item(restaurant):
    order = _order(
        items=[
            _order_item(
                _menu_item("Classic Burger", 35.0),
                quantity=1,
                unit_price=40.0,  # 35.00 base + 5.00 Extra Cheese
                modifier_names=["Extra Cheese", "Algérienne"],
            )
        ],
        total_price=40.0,
    )

    text = build_order_receipt_text(order, restaurant)

    assert text == (
        "1x Classic Burger - 40.00 MAD\n"
        "   + Extra Cheese\n"
        "   + Algérienne\n"
        "\n"
        "Total: 40.00 MAD"
    )


def test_receipt_is_plain_text_with_no_monospace_formatting(restaurant):
    order = _order(
        items=[_order_item(_menu_item("Fries", 20.0), modifier_names=["Ketchup"])],
        total_price=20.0,
        delivery_fee=5.0,
        customer_notes="No salt",
    )

    text = build_order_receipt_text(order, restaurant)

    assert "```" not in text
    assert "\t" not in text


# ── Oversized order truncation ────────────────────────────────────────────

def _oversized_order():
    items = [
        _order_item(
            _menu_item(f"Very Long Menu Item Name Number {i:02d} With Padding", 25.0),
            quantity=2,
            modifier_names=["Extra Cheese", "Spicy Harissa Sauce"],
        )
        for i in range(40)
    ]
    return _order(items=items, total_price=2000.0, delivery_fee=15.0)


def test_oversized_order_is_truncated_under_the_cap(restaurant):
    order = _oversized_order()

    text = build_order_receipt_text(order, restaurant)

    assert len(text) <= RECEIPT_MAX_CHARS


def test_oversized_order_keeps_totals_and_reports_the_remainder(restaurant):
    order = _oversized_order()

    text = build_order_receipt_text(order, restaurant)

    # The money lines survive truncation — they are the point of the receipt.
    assert "Total: 2000.00 MAD" in text
    assert "Delivery Fee: 15.00 MAD" in text
    # And the customer is told how many items were dropped.
    assert "more item(s)" in text
    shown = text.count(" - ")
    assert f"…and {40 - shown} more item(s)" in text


def test_untruncated_order_has_no_remainder_notice(restaurant):
    order = _order(
        items=[_order_item(_menu_item("Fries", 20.0))],
        total_price=20.0,
    )
    assert "more item(s)" not in build_order_receipt_text(order, restaurant)


def test_truncation_notice_promises_no_channel_geqo_lacks(restaurant):
    """
    GEQO has no customer-facing email or printed receipt today (EmailService
    only mails restaurant owners/admins), so the notice must not promise one.
    """
    text = build_order_receipt_text(_oversized_order(), restaurant)

    assert "email" not in text.lower()
    assert "printed" not in text.lower()


# ── Degenerate input ──────────────────────────────────────────────────────

def test_order_with_no_items_still_renders_a_total(restaurant):
    order = _order(items=[], total_price=0.0)
    assert build_order_receipt_text(order, restaurant) == "Total: 0.00 MAD"


def test_item_with_missing_menu_item_does_not_raise(restaurant):
    line = OrderItem(menu_item=None, quantity=1, unit_price=12.0)
    line.modifiers = []
    order = _order(items=[line], total_price=12.0)

    assert "1x Item - 12.00 MAD" in build_order_receipt_text(order, restaurant)
