"""
Submits GEQO's six fixed order-lifecycle templates to a restaurant's own WABA.

Each restaurant has its own WhatsApp Business Account (ADR001), so templates are
registered per-restaurant against Meta's Message Template Management API:

    POST https://graph.facebook.com/v21.0/{waba_id}/message_templates

Note the identifier: this endpoint keys off the restaurant's **waba_id**, NOT
its phone_number_id. They are different Meta identifiers — the WABA owns the
template catalog, the phone number sends messages — and using one where the
other is expected is the most common failure mode here.

This is also the concrete, recordable action GEQO demonstrates for the
`whatsapp_business_management` permission in Meta App Review.

Kept out of app/services/whatsapp.py, which stays a pure message-transport layer.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List

import httpx
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageTemplateStatus, Restaurant, RestaurantMessageTemplate
from app.services.message_templates import (
    ORDER_LIFECYCLE_TEMPLATES,
    build_meta_template_payload,
)

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"

# Meta reports more review states than GEQO tracks; anything that is not a
# settled approve/reject is treated as still pending.
_META_STATUS_MAP = {
    "APPROVED": MessageTemplateStatus.APPROVED,
    "REJECTED": MessageTemplateStatus.REJECTED,
    "PENDING": MessageTemplateStatus.PENDING,
    "PENDING_DELETION": MessageTemplateStatus.PENDING,
    "IN_APPEAL": MessageTemplateStatus.PENDING,
    "PAUSED": MessageTemplateStatus.PENDING,
    "DISABLED": MessageTemplateStatus.REJECTED,
}

# Meta's "a template with this name and language already exists" error. Not a
# failure for our purposes — the template is registered, which is the goal.
_DUPLICATE_NAME_ERROR_CODE = 2388023


def _map_meta_status(raw: str) -> MessageTemplateStatus:
    return _META_STATUS_MAP.get((raw or "").upper(), MessageTemplateStatus.PENDING)


async def _upsert_template_record(
    db: AsyncSession,
    restaurant_id: int,
    template_key: str,
    status: MessageTemplateStatus,
    meta_template_id: str = None,
) -> RestaurantMessageTemplate:
    """Insert or refresh this restaurant's registration row for one template."""
    existing = (
        await db.execute(
            select(RestaurantMessageTemplate).where(
                RestaurantMessageTemplate.restaurant_id == restaurant_id,
                RestaurantMessageTemplate.template_key == template_key,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.meta_status = status
        existing.submitted_at = datetime.utcnow()
        if meta_template_id:
            existing.meta_template_id = meta_template_id
        return existing

    record = RestaurantMessageTemplate(
        restaurant_id=restaurant_id,
        template_key=template_key,
        meta_status=status,
        meta_template_id=meta_template_id,
    )
    db.add(record)
    return record


async def provision_restaurant_templates(
    db: AsyncSession, restaurant: Restaurant
) -> List[Dict]:
    """
    Submit all six templates to `restaurant`'s WABA and mirror the outcome into
    restaurant_message_templates.

    Returns one result dict per template. A single template failing does NOT
    abort the batch — a partial success is far more useful to the admin than an
    all-or-nothing error, and re-running the endpoint is safe (Meta's duplicate
    -name error is treated as already-registered).

    Raises ValueError if the restaurant has no waba_id, since nothing can be
    submitted without it.
    """
    if not restaurant.waba_id:
        raise ValueError(
            "Restaurant has no Meta WABA ID. Set it on the restaurant before "
            "provisioning message templates."
        )

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{restaurant.waba_id}/message_templates"
    headers = {
        "Authorization": f"Bearer {restaurant.api_token}",
        "Content-Type": "application/json",
    }

    results: List[Dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for template in ORDER_LIFECYCLE_TEMPLATES:
            key = template["key"]
            payload = build_meta_template_payload(template)

            try:
                response = await client.post(url, headers=headers, json=payload)
                body = {}
                try:
                    body = response.json() or {}
                except ValueError:
                    pass

                if response.status_code in (200, 201):
                    status = _map_meta_status(body.get("status", "PENDING"))
                    await _upsert_template_record(
                        db, restaurant.id, key, status, body.get("id")
                    )
                    results.append(
                        {
                            "template_key": key,
                            "ok": True,
                            "meta_status": status.value,
                            "meta_template_id": body.get("id"),
                        }
                    )
                    continue

                error = body.get("error", {}) or {}
                if error.get("code") == _DUPLICATE_NAME_ERROR_CODE:
                    # Already on this WABA from an earlier run — record it as
                    # submitted rather than reporting a spurious failure.
                    await _upsert_template_record(
                        db, restaurant.id, key, MessageTemplateStatus.PENDING
                    )
                    results.append(
                        {
                            "template_key": key,
                            "ok": True,
                            "meta_status": MessageTemplateStatus.PENDING.value,
                            "detail": "Already registered on this WABA.",
                        }
                    )
                    continue

                message = error.get("message") or response.text
                logger.error(
                    "[template_provisioning] Meta rejected %s for restaurant %s: %s %s",
                    key, restaurant.id, response.status_code, message,
                )
                results.append(
                    {
                        "template_key": key,
                        "ok": False,
                        "error": message,
                        "status_code": response.status_code,
                    }
                )

            except httpx.HTTPError as exc:
                logger.error(
                    "[template_provisioning] Network error submitting %s for restaurant %s: %s",
                    key, restaurant.id, exc,
                )
                results.append({"template_key": key, "ok": False, "error": str(exc)})

    await db.commit()
    return results
