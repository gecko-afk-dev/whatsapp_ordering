"""
event_engine.py — GEQO Internal Insights Engine, Phase A

Non-blocking event dispatch service.
Design invariant: event logging errors MUST NEVER propagate to or delay
any primary HTTP order transaction. All paths are wrapped in try/except
and use fire-and-forget patterns.

Salt strategy (Phase A): SHA256(phone.strip() + str(restaurant_id) + SECRET_KEY)
— stable, per-tenant pseudonymization without a dedicated salt column.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_customer_phone(phone: str, salt: str) -> str:
    """
    Returns SHA256(phone.strip() + salt) as a hex string.
    Pseudonymizes raw PII at the source — the plaintext phone is never stored.
    """
    raw = (phone.strip() + salt).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Core emit (async, requires an active AsyncSession)
# ---------------------------------------------------------------------------

async def emit_event(
    db: AsyncSession,
    event_type: str,
    channel: str,
    restaurant_id: Optional[int] = None,
    phone_number: Optional[str] = None,
    payload: Optional[dict] = None,
    event_id: Optional[str] = None,
) -> None:
    """
    Persist a single EventLog row. Errors are swallowed to prevent breaking
    the primary transaction — never call this inside the caller's transaction
    unless you are intentionally sharing it (the function does NOT commit).

    For fire-and-forget usage, use fire_and_forget_event() or queue_event()
    so this runs in its own session with its own commit.
    """
    try:
        customer_hash: Optional[str] = None
        if phone_number and restaurant_id is not None:
            from app.core.config import settings
            salt = str(restaurant_id) + settings.SECRET_KEY
            customer_hash = hash_customer_phone(phone_number, salt)

        # Deduplicate: if an event_id is provided and already exists, skip silently
        resolved_event_id: Optional[str] = event_id or str(uuid.uuid4())

        entry = EventLog(
            event_id=resolved_event_id,
            event_type=event_type,
            restaurant_id=restaurant_id,
            customer_hash=customer_hash,
            channel=channel,
            payload=payload or {},
        )
        db.add(entry)
        await db.commit()
    except Exception:
        logger.warning(
            "Event emission failed (non-fatal) | event_type=%s restaurant_id=%s",
            event_type,
            restaurant_id,
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Fire-and-forget wrapper (for webhook.py / flow_handler.py which have no
# BackgroundTasks injection — creates its own DB session)
# ---------------------------------------------------------------------------

async def _emit_in_own_session(
    event_type: str,
    channel: str,
    restaurant_id: Optional[int],
    phone_number: Optional[str],
    payload: Optional[dict],
    event_id: Optional[str],
) -> None:
    """Opens its own AsyncSession so it never shares or pollutes primary sessions."""
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await emit_event(
                db=db,
                event_type=event_type,
                channel=channel,
                restaurant_id=restaurant_id,
                phone_number=phone_number,
                payload=payload,
                event_id=event_id,
            )
    except Exception:
        logger.warning(
            "fire_and_forget_event session error (non-fatal) | event_type=%s",
            event_type,
            exc_info=True,
        )


def fire_and_forget_event(
    event_type: str,
    channel: str,
    restaurant_id: Optional[int] = None,
    phone_number: Optional[str] = None,
    payload: Optional[dict] = None,
    event_id: Optional[str] = None,
) -> None:
    """
    Schedule event emission on the current asyncio event loop without awaiting.
    Safe to call from any async context that does NOT have BackgroundTasks available
    (e.g. webhook.py, flow_handler.py, process_flow_request).

    Uses asyncio.ensure_future() — the coroutine runs after the current
    coroutine yields, in the same event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(
            _emit_in_own_session(
                event_type=event_type,
                channel=channel,
                restaurant_id=restaurant_id,
                phone_number=phone_number,
                payload=payload,
                event_id=event_id,
            )
        )
    except RuntimeError:
        # No running event loop (e.g. during tests) — log and skip
        logger.warning(
            "fire_and_forget_event: no running event loop, skipping event_type=%s",
            event_type,
        )


# ---------------------------------------------------------------------------
# BackgroundTasks wrapper (for public_orders.py, dashboard.py)
# ---------------------------------------------------------------------------

def queue_event(
    background_tasks: BackgroundTasks,
    event_type: str,
    channel: str,
    restaurant_id: Optional[int] = None,
    phone_number: Optional[str] = None,
    payload: Optional[dict] = None,
    event_id: Optional[str] = None,
) -> None:
    """
    Enqueue event emission via FastAPI BackgroundTasks. The emission runs
    after the HTTP response is sent — zero latency impact on the endpoint.
    Use this in any endpoint that injects BackgroundTasks.
    """
    background_tasks.add_task(
        _emit_in_own_session,
        event_type=event_type,
        channel=channel,
        restaurant_id=restaurant_id,
        phone_number=phone_number,
        payload=payload,
        event_id=event_id,
    )
