"""
compliance.py — Public CNDP Law 09-08 compliance endpoints.

Currently: data-deletion requests. Kept separate from beta.py (unrelated
business concern) so the compliance surface can grow (e.g. consent export)
without crowding the beta-signup flow.
"""

import logging
import time
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException, Request, Depends, status, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models import DataDeletionRequest, DataDeletionStatus
from app.services.email import EmailService
from app.services.event_engine import queue_event

router = APIRouter(tags=["Compliance"])
logger = logging.getLogger(__name__)


class DataDeletionRequestPayload(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+?[0-9]{9,15}$")
    reason: str = Field(default="", max_length=1000)


# Simple in-memory rate limiter — same pattern as beta.py's check_rate_limit.
# Low-volume, abuse-resistant endpoint; a distributed limiter is overkill here.
rate_limit_cache: Dict[str, Tuple[int, float]] = {}
RATE_LIMIT_MAX_REQUESTS = 5
RATE_LIMIT_WINDOW_SECONDS = 300


async def check_deletion_rate_limit(request: Request):
    client_ip = request.headers.get("cf-connecting-ip")
    if not client_ip:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    current_time = time.time()
    if client_ip in rate_limit_cache:
        count, reset_time = rate_limit_cache[client_ip]
        if current_time > reset_time:
            rate_limit_cache[client_ip] = (1, current_time + RATE_LIMIT_WINDOW_SECONDS)
        else:
            if count >= RATE_LIMIT_MAX_REQUESTS:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")
            rate_limit_cache[client_ip] = (count + 1, reset_time)
    else:
        rate_limit_cache[client_ip] = (1, current_time + RATE_LIMIT_WINDOW_SECONDS)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@router.post(
    "/data-deletion-request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(check_deletion_rate_limit)],
    summary="CNDP Law 09-08 Data Erasure Request",
    description="""
    Public, unauthenticated endpoint backing the marketing site's data-deletion
    form. Records an auditable, 30-day-SLA erasure request and notifies GEQO
    compliance staff by email.

    This endpoint does NOT itself delete any data — actual erasure across the
    operational tables (Customer, Order, EventLog pseudonym mappings, etc.)
    spans multiple tenants' data and is a deliberate, manual admin action
    performed within the 30-day window, not an automatic side effect of this
    call. Automating full cross-tenant erasure safely is a separate, larger
    piece of work than restoring this endpoint's existence.
    """,
)
async def request_data_deletion(
    payload: DataDeletionRequestPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    phone = payload.phone_number.strip()
    reason = payload.reason.strip() if payload.reason else None

    # Avoid duplicate admin noise: reuse an existing PENDING request for the same number
    # rather than raising an error — a customer retrying the form shouldn't be blocked.
    existing = await db.execute(
        select(DataDeletionRequest).where(
            DataDeletionRequest.phone_number == phone,
            DataDeletionRequest.status == DataDeletionStatus.PENDING,
        )
    )
    existing_request = existing.scalar_one_or_none()
    if existing_request:
        return {
            "message": "A deletion request for this number is already pending review.",
            "request_id": existing_request.id,
        }

    new_request = DataDeletionRequest(phone_number=phone, reason=reason)
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)

    # Notify compliance staff inline, but never fail the customer-facing request
    # over an email hiccup — the DB record (not the email) is what proves the
    # 30-day SLA clock started. A failed notification is logged for manual
    # follow-up rather than surfaced to the requester as an error.
    try:
        notified = await EmailService.send_admin_data_deletion_notification(
            phone_number=phone,
            reason=reason or "(not provided)",
            request_id=new_request.id,
        )
    except Exception:
        logger.exception("Data deletion admin notification failed for request_id=%s", new_request.id)
        notified = False

    if not notified:
        logger.warning(
            "Data deletion request %s recorded but admin notification email failed — "
            "requires manual follow-up to meet the 30-day SLA.",
            new_request.id,
        )

    # Audit trail — platform-level event, no restaurant scope (a phone number
    # may have ordered from more than one tenant).
    queue_event(
        background_tasks,
        event_type="customer.data_deletion_requested",
        channel="system",
        phone_number=phone,
        payload={"request_id": new_request.id},
    )

    return {
        "message": "Your data deletion request has been received and will be processed within 30 days.",
        "request_id": new_request.id,
    }
