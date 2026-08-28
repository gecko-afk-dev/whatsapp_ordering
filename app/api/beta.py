import logging
from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Literal, Optional, Tuple
from datetime import datetime, timedelta
import os
import time

from app.core.database import AsyncSessionLocal
from app.models import BetaCard, BetaSignup, BetaCardStatus
from app.services.email import EmailService

router = APIRouter(tags=["Beta Signup"])
logger = logging.getLogger(__name__)

class BetaSignupRequest(BaseModel):
    manager_name: str = Field(..., min_length=2, max_length=150)
    restaurant_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    whatsapp_number: str = Field(..., pattern=r"^\+?[0-9]{9,15}$")
    card_code: str = Field(..., pattern=r"^GEQO-[A-Z0-9]{6}$")
    locale: str = Field(default="fr", pattern=r"^(en|fr|ar)$")


class ContactRequest(BaseModel):
    category: Literal["sales", "support"]
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    whatsapp: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=5000)
    # Hidden anti-spam field — the real form never populates this. Bots that
    # auto-fill every field will, so a non-empty value marks the submission
    # as spam (see check_contact_rate_limit / contact_form below).
    honeypot: Optional[str] = ""

# Simple in-memory rate limiter: IP -> (count, reset_time)
rate_limit_cache: Dict[str, Tuple[int, float]] = {}
RATE_LIMIT_ENABLED = os.getenv("BETA_SIGNUP_RATE_LIMIT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("BETA_SIGNUP_RATE_LIMIT_MAX_REQUESTS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("BETA_SIGNUP_RATE_LIMIT_WINDOW_SECONDS", "300"))

def _get_client_ip(request: Request) -> str:
    """Retrieve the real client IP by checking proxy headers first.
    Cloudflare adds 'cf-connecting-ip', and reverse proxies add 'x-forwarded-for'.
    """
    client_ip = request.headers.get("cf-connecting-ip")
    if not client_ip:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            # X-Forwarded-For can contain multiple IPs; the first one is the client.
            client_ip = x_forwarded_for.split(",")[0].strip()

    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    return client_ip


async def check_rate_limit(request: Request):
    if not RATE_LIMIT_ENABLED:
        return

    client_ip = _get_client_ip(request)
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


# ---------------------------------------------------------------------------
# Rate limiting — contact form submissions
# ---------------------------------------------------------------------------
# Mirrors the lightweight in-memory sliding-window pattern introduced for
# /admin/login and /auth/forgot-password (see app/api/admin.py's
# _login_rate_limited and app/api/auth.py's _forgot_password_rate_limited).
# Keyed by client IP rather than email/account, since an anonymous contact-form
# submitter has no stable identity to key on the way a login attempt does.
_CONTACT_ATTEMPT_LOG: Dict[str, list] = {}
CONTACT_RATE_LIMIT_WINDOW_SECONDS = 600
CONTACT_RATE_LIMIT_MAX_ATTEMPTS = 5


def _contact_rate_limited(ip: str) -> bool:
    """Returns True if this IP has exceeded the contact-form rate limit."""
    now = time.time()
    attempts = [
        t for t in _CONTACT_ATTEMPT_LOG.get(ip, [])
        if now - t < CONTACT_RATE_LIMIT_WINDOW_SECONDS
    ]
    if len(attempts) >= CONTACT_RATE_LIMIT_MAX_ATTEMPTS:
        _CONTACT_ATTEMPT_LOG[ip] = attempts
        return True
    attempts.append(now)
    _CONTACT_ATTEMPT_LOG[ip] = attempts
    return False


async def check_contact_rate_limit(request: Request):
    if _contact_rate_limited(_get_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a few minutes and try again.",
        )


async def send_signup_emails_task(signup_id: int, manager_name: str, restaurant_name: str, email: str, whatsapp_number: str, card_code: str, locale: str):
    # Fire confirmation email to user
    email_success = await EmailService.send_beta_confirmation(
        email=email,
        manager_name=manager_name,
        restaurant_name=restaurant_name,
        locale=locale
    )
    
    # Fire notification email to admin
    admin_email_success = await EmailService.send_admin_signup_notification(
        manager_name=manager_name,
        restaurant_name=restaurant_name,
        email=email,
        whatsapp_number=whatsapp_number,
        card_code=card_code
    )
    
    if email_success and admin_email_success:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BetaSignup).where(BetaSignup.id == signup_id))
            signup = result.scalar_one_or_none()
            if signup:
                signup.confirmation_sent = True
                await db.commit()
        return True

    return False

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.post("/beta-signup", status_code=status.HTTP_201_CREATED, dependencies=[Depends(check_rate_limit)])
async def beta_signup(req: BetaSignupRequest, db: AsyncSession = Depends(get_db)):
    # Clean input strings
    req.manager_name = req.manager_name.strip()
    req.restaurant_name = req.restaurant_name.strip()

    # 1. Validate card exists
    result = await db.execute(select(BetaCard).where(BetaCard.card_code == req.card_code))
    card = result.scalar_one_or_none()
    
    if not card:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
        
    # 2. Validate card is available
    if card.status != BetaCardStatus.AVAILABLE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This card has already been redeemed")
        
    # 3. Check duplicate email
    result = await db.execute(select(BetaSignup).where(BetaSignup.email == req.email))
    existing_signup = result.scalar_one_or_none()
    if existing_signup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This email is already registered")

    # 4. Create BetaSignup record
    # trial_days lives on the card so specific hand-pitched cards can be set
    # to 30 before being handed out, while the default stays 14 for everyone else.
    new_signup = BetaSignup(
        card_id=card.id,
        manager_name=req.manager_name,
        restaurant_name=req.restaurant_name,
        email=req.email,
        whatsapp_number=req.whatsapp_number,
        locale=req.locale,
        trial_ends_at=datetime.utcnow() + timedelta(days=card.trial_days)
    )
    db.add(new_signup)

    # 5. Update BetaCard status
    card.status = BetaCardStatus.CLAIMED
    card.claimed_at = datetime.utcnow()
    
    # 6. Save changes to DB first so signup is immediately recorded
    await db.commit()
    await db.refresh(new_signup)
    
    # 7. Send the confirmation emails inline so the signup is not reported as successful
    # unless the delivery path has actually been attempted.
    try:
        email_sent = await send_signup_emails_task(
            signup_id=new_signup.id,
            manager_name=req.manager_name,
            restaurant_name=req.restaurant_name,
            email=req.email,
            whatsapp_number=req.whatsapp_number,
            card_code=req.card_code,
            locale=req.locale
        )
    except Exception as exc:
        logger.exception("Beta signup email dispatch failed for %s: %s", req.email, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signup was created but confirmation email could not be sent"
        ) from exc

    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signup was created but confirmation email could not be sent"
        )

    return {"message": "Signup successful"}


@router.post("/contact", dependencies=[Depends(check_contact_rate_limit)])
async def contact_form(req: ContactRequest):
    """Public Contact Us form (marketing site). Email-forward only — no
    database persistence for v1. Routes to sales@mygeqo.com or
    support@mygeqo.com depending on category, with reply-to set to the
    submitter's own email.
    """
    # Honeypot: a hidden field real users never fill in. If it's non-empty,
    # a bot filled every field on the form — silently accept without
    # sending any email or revealing to the bot that it was caught.
    if req.honeypot:
        logger.info("Contact form honeypot triggered — submission discarded")
        return {"success": True}

    try:
        email_sent = await EmailService.send_contact_message(
            category=req.category,
            name=req.name.strip(),
            email=req.email,
            whatsapp=req.whatsapp.strip() if req.whatsapp else None,
            message=req.message.strip(),
        )
    except Exception as exc:
        logger.exception("Contact form email dispatch failed for %s: %s", req.email, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later."
        ) from exc

    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later."
        )

    return {"success": True}
