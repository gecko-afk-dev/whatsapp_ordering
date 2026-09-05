"""
Tests for the fixed WhatsApp order-lifecycle template catalog and its
per-restaurant provisioning against Meta's Template Management API.
"""
import re
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy.future import select

from app.models import MessageTemplateStatus, Restaurant, RestaurantMessageTemplate
from app.services.message_templates import (
    ORDER_LIFECYCLE_TEMPLATES,
    TEMPLATE_CATEGORY,
    TEMPLATE_KEYS,
    TEMPLATE_LANGUAGE,
    TemplateKey,
    build_meta_template_payload,
)
from app.services.template_provisioning import provision_restaurant_templates


# ── Catalog integrity ─────────────────────────────────────────────────────

def test_catalog_covers_all_six_lifecycle_steps():
    assert TEMPLATE_KEYS == [
        TemplateKey.ORDER_CONFIRMED,
        TemplateKey.ORDER_IN_KITCHEN,
        TemplateKey.ORDER_READY_PICKUP,
        TemplateKey.ORDER_DISPATCHED,
        TemplateKey.ORDER_DELIVERED,
        TemplateKey.ORDER_CANCELLED,
    ]


def test_every_template_is_utility_category():
    """A promotional reclassification is what puts a WABA at risk."""
    for template in ORDER_LIFECYCLE_TEMPLATES:
        assert build_meta_template_payload(template)["category"] == "UTILITY"
    assert TEMPLATE_CATEGORY == "UTILITY"


@pytest.mark.parametrize("template", ORDER_LIFECYCLE_TEMPLATES, ids=lambda t: t["key"])
def test_placeholder_arity_matches_declared_variables_and_examples(template):
    """
    Meta rejects a send whose parameter count differs from the registered
    template, so body/variables/example must agree exactly.
    """
    placeholders = sorted({int(n) for n in re.findall(r"\{\{(\d+)\}\}", template["body"])})

    assert placeholders == list(range(1, len(placeholders) + 1)), "must be 1..N with no gaps"
    assert len(placeholders) == len(template["variables"])
    assert len(placeholders) == len(template["example"])


@pytest.mark.parametrize("template", ORDER_LIFECYCLE_TEMPLATES, ids=lambda t: t["key"])
def test_template_name_is_valid_for_meta(template):
    """Meta template names: lowercase letters, digits and underscores only."""
    assert re.fullmatch(r"[a-z0-9_]+", template["key"])


@pytest.mark.parametrize("template", ORDER_LIFECYCLE_TEMPLATES, ids=lambda t: t["key"])
def test_every_template_is_bilingual_en_plus_darija(template):
    """Each body carries its own Arabic-script line — no per-language variants."""
    assert re.search(r"[؀-ۿ]", template["body"]), "no Arabic script found"


def test_order_confirmed_carries_the_receipt_variable():
    template = next(t for t in ORDER_LIFECYCLE_TEMPLATES if t["key"] == TemplateKey.ORDER_CONFIRMED)
    assert template["variables"] == ["order_code", "receipt_block"]


def test_order_dispatched_carries_driver_and_pin():
    template = next(t for t in ORDER_LIFECYCLE_TEMPLATES if t["key"] == TemplateKey.ORDER_DISPATCHED)
    assert template["variables"] == ["order_code", "driver_name", "delivery_pin"]


def test_meta_payload_shape():
    payload = build_meta_template_payload(
        next(t for t in ORDER_LIFECYCLE_TEMPLATES if t["key"] == TemplateKey.ORDER_IN_KITCHEN)
    )
    assert payload["name"] == "order_in_kitchen"
    assert payload["language"] == TEMPLATE_LANGUAGE
    assert payload["components"][0]["type"] == "BODY"
    # Meta wants examples nested one level deeper than feels natural.
    assert payload["components"][0]["example"]["body_text"] == [["A4F9K2"]]


def test_bodies_stay_under_the_whatsapp_limit_before_variables():
    for template in ORDER_LIFECYCLE_TEMPLATES:
        assert len(template["body"]) < 1024


# ── Provisioning against Meta ─────────────────────────────────────────────

def _mock_response(status_code, json_body):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    response.text = str(json_body)
    return response


def _patched_client(responses):
    """Patch httpx.AsyncClient so POST returns queued responses in order."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=responses)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("app.services.template_provisioning.httpx.AsyncClient", return_value=ctx), client


@pytest.mark.asyncio
async def test_provisioning_requires_a_waba_id(db_session, seed_restaurant):
    seed_restaurant.waba_id = None

    with pytest.raises(ValueError, match="WABA ID"):
        await provision_restaurant_templates(db_session, seed_restaurant)


@pytest.mark.asyncio
async def test_provisioning_submits_all_six_and_records_them(db_session, seed_restaurant):
    seed_restaurant.waba_id = "123456789"
    responses = [
        _mock_response(200, {"id": f"tpl_{i}", "status": "PENDING"})
        for i in range(len(ORDER_LIFECYCLE_TEMPLATES))
    ]
    patcher, client = _patched_client(responses)

    with patcher:
        results = await provision_restaurant_templates(db_session, seed_restaurant)

    assert len(results) == 6
    assert all(r["ok"] for r in results)

    # Every call targets the WABA ID — not the phone number ID.
    for call in client.post.call_args_list:
        assert "123456789/message_templates" in call.args[0]
        assert "fake_phone_id" not in call.args[0]

    rows = (await db_session.execute(
        select(RestaurantMessageTemplate).where(
            RestaurantMessageTemplate.restaurant_id == seed_restaurant.id
        )
    )).scalars().all()
    assert {r.template_key for r in rows} == set(TEMPLATE_KEYS)
    assert all(r.meta_status == MessageTemplateStatus.PENDING for r in rows)


@pytest.mark.asyncio
async def test_approved_status_from_meta_is_mapped(db_session, seed_restaurant):
    seed_restaurant.waba_id = "999"
    responses = [
        _mock_response(200, {"id": f"tpl_{i}", "status": "APPROVED"})
        for i in range(len(ORDER_LIFECYCLE_TEMPLATES))
    ]
    patcher, _ = _patched_client(responses)

    with patcher:
        await provision_restaurant_templates(db_session, seed_restaurant)

    rows = (await db_session.execute(
        select(RestaurantMessageTemplate).where(
            RestaurantMessageTemplate.restaurant_id == seed_restaurant.id
        )
    )).scalars().all()
    assert all(r.meta_status == MessageTemplateStatus.APPROVED for r in rows)


@pytest.mark.asyncio
async def test_duplicate_name_is_treated_as_already_registered(db_session, seed_restaurant):
    """Re-running the endpoint must not report spurious failures."""
    seed_restaurant.waba_id = "555"
    duplicate = _mock_response(400, {"error": {"code": 2388023, "message": "already exists"}})
    patcher, _ = _patched_client([duplicate] * len(ORDER_LIFECYCLE_TEMPLATES))

    with patcher:
        results = await provision_restaurant_templates(db_session, seed_restaurant)

    assert all(r["ok"] for r in results)
    assert all("Already registered" in r["detail"] for r in results)


@pytest.mark.asyncio
async def test_one_failure_does_not_abort_the_batch(db_session, seed_restaurant):
    seed_restaurant.waba_id = "777"
    responses = [_mock_response(400, {"error": {"code": 100, "message": "bad param"}})]
    responses += [
        _mock_response(200, {"id": f"tpl_{i}", "status": "PENDING"})
        for i in range(len(ORDER_LIFECYCLE_TEMPLATES) - 1)
    ]
    patcher, _ = _patched_client(responses)

    with patcher:
        results = await provision_restaurant_templates(db_session, seed_restaurant)

    assert results[0]["ok"] is False
    assert results[0]["error"] == "bad param"
    assert all(r["ok"] for r in results[1:])

    # The five that succeeded are still recorded.
    rows = (await db_session.execute(
        select(RestaurantMessageTemplate).where(
            RestaurantMessageTemplate.restaurant_id == seed_restaurant.id
        )
    )).scalars().all()
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_reprovisioning_updates_rather_than_duplicates(db_session, seed_restaurant):
    seed_restaurant.waba_id = "888"

    def fresh(status):
        return [
            _mock_response(200, {"id": f"tpl_{i}", "status": status})
            for i in range(len(ORDER_LIFECYCLE_TEMPLATES))
        ]

    patcher, _ = _patched_client(fresh("PENDING"))
    with patcher:
        await provision_restaurant_templates(db_session, seed_restaurant)

    patcher, _ = _patched_client(fresh("APPROVED"))
    with patcher:
        await provision_restaurant_templates(db_session, seed_restaurant)

    rows = (await db_session.execute(
        select(RestaurantMessageTemplate).where(
            RestaurantMessageTemplate.restaurant_id == seed_restaurant.id
        )
    )).scalars().all()
    assert len(rows) == 6, "unique (restaurant_id, template_key) must prevent duplicates"
    assert all(r.meta_status == MessageTemplateStatus.APPROVED for r in rows)


# ── Transport: send_template_message payload ──────────────────────────────

@pytest.mark.asyncio
async def test_send_template_message_builds_a_valid_template_payload():
    from app.services.whatsapp import WhatsAppService

    service = WhatsAppService(token="t", phone_id="p")
    with patch.object(service, "_post", new_callable=AsyncMock) as mock_post:
        await service.send_template_message(
            "212600000000", TemplateKey.ORDER_DISPATCHED, ["A4F9K2", "Youssef", "482913"]
        )

    payload = mock_post.call_args.args[0]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "order_dispatched"
    assert payload["template"]["language"]["code"] == TEMPLATE_LANGUAGE
    # Positional body parameters, in order, all stringified.
    assert payload["template"]["components"] == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "A4F9K2"},
                {"type": "text", "text": "Youssef"},
                {"type": "text", "text": "482913"},
            ],
        }
    ]


@pytest.mark.asyncio
async def test_send_template_message_omits_components_when_no_params():
    from app.services.whatsapp import WhatsAppService

    service = WhatsAppService(token="t", phone_id="p")
    with patch.object(service, "_post", new_callable=AsyncMock) as mock_post:
        await service.send_template_message("212600000000", "some_template")

    assert mock_post.call_args.args[0]["template"]["components"] == []


# ── Endpoint RBAC ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provision_templates_rejects_kitchen_staff(async_client, auth_tokens, seed_restaurant):
    res = await async_client.post(
        f"/api/v1/admin/restaurant/{seed_restaurant.id}/provision-templates",
        headers=auth_tokens["staff"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_provision_templates_rejects_cashier(async_client, auth_tokens, seed_restaurant):
    """Write action: get_manager_or_admin, matching the drivers.py precedent."""
    res = await async_client.post(
        f"/api/v1/admin/restaurant/{seed_restaurant.id}/provision-templates",
        headers=auth_tokens["cashier"],
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_provision_templates_without_waba_id_is_a_400_not_a_500(
    async_client, auth_tokens, seed_restaurant, db_session
):
    seed_restaurant.waba_id = None
    await db_session.commit()

    res = await async_client.post(
        f"/api/v1/admin/restaurant/{seed_restaurant.id}/provision-templates",
        headers=auth_tokens["admin"],
    )
    assert res.status_code == 400
    assert "WABA ID" in res.json()["detail"]


@pytest.mark.asyncio
async def test_message_templates_preview_flags_missing_waba_id(
    async_client, auth_tokens, seed_restaurant, db_session
):
    seed_restaurant.waba_id = None
    await db_session.commit()

    res = await async_client.get(
        "/api/v1/admin/restaurant/message-templates", headers=auth_tokens["owner"]
    )
    assert res.status_code == 200
    body = res.json()
    assert body["waba_id_missing"] is True
    # The catalog copy is still returned so the UI can render the preview.
    assert [t["key"] for t in body["templates"]] == TEMPLATE_KEYS
    # Never submitted yet.
    assert all(t["meta_status"] is None for t in body["templates"])


@pytest.mark.asyncio
async def test_message_templates_preview_is_readable_by_cashier(
    async_client, auth_tokens, seed_restaurant, db_session
):
    """Read-only preview page is available to cashier and above."""
    from app.models import User as UserModel

    # The shared conftest cashier is not attached to a restaurant; attach it so
    # this exercises the role gate rather than the "no restaurant" guard.
    cashier = (await db_session.execute(
        select(UserModel).where(UserModel.email == "cashier@example.com")
    )).scalar_one()
    cashier.restaurant_id = seed_restaurant.id
    await db_session.commit()

    res = await async_client.get(
        "/api/v1/admin/restaurant/message-templates", headers=auth_tokens["cashier"]
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_preview_exposes_no_way_to_edit_template_bodies(async_client, auth_tokens, seed_restaurant):
    """
    The page is intentionally NOT an editor: template bodies are platform-owned.
    There must be no PUT/PATCH/POST route for template content.
    """
    from app.main import app

    content_routes = [
        (sorted(r.methods), r.path)
        for r in app.routes
        if "message-template" in getattr(r, "path", "")
    ]
    assert content_routes == [(["GET"], "/api/v1/admin/restaurant/message-templates")]
