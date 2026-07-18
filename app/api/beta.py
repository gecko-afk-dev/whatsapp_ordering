from fastapi import APIRouter, HTTPException, Request, Depends, status, BackgroundTasks
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Tuple
from datetime import datetime
import os
import time

from app.core.database import AsyncSessionLocal
from app.models import BetaCard, BetaSignup, BetaCardStatus
from app.services.email import EmailService

router = APIRouter(tags=["Beta Signup"])

class BetaSignupRequest(BaseModel):
    manager_name: str = Field(..., min_length=2, max_length=150)
    restaurant_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    whatsapp_number: str = Field(..., pattern=r"^\+?[0-9]{9,15}$")
    card_code: str = Field(..., pattern=r"^GEQO-[A-Z0-9]{6}$")
    locale: str = Field(default="fr", pattern=r"^(en|fr|ar)$")

# Simple in-memory rate limiter: IP -> (count, reset_time)
rate_limit_cache: Dict[str, Tuple[int, float]] = {}
RATE_LIMIT_ENABLED = os.getenv("BETA_SIGNUP_RATE_LIMIT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("BETA_SIGNUP_RATE_LIMIT_MAX_REQUESTS", "20"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("BETA_SIGNUP_RATE_LIMIT_WINDOW_SECONDS", "300"))

async def check_rate_limit(request: Request):
    if not RATE_LIMIT_ENABLED:
        return

    # Retrieve the real client IP by checking proxy headers first.
    # Cloudflare adds 'cf-connecting-ip', and reverse proxies add 'x-forwarded-for'.
    client_ip = request.headers.get("cf-connecting-ip")
    if not client_ip:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            # X-Forwarded-For can contain multiple IPs; the first one is the client.
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


async def send_signup_emails_task(signup_id: int, manager_name: str, restaurant_name: str, email: str, whatsapp_number: str, card_code: str, locale: str):
    # Fire confirmation email to user
    email_success = await EmailService.send_beta_confirmation(
        email=email,
        manager_name=manager_name,
        restaurant_name=restaurant_name,
        locale=locale
    )
    
    # Fire notification email to admin
    await EmailService.send_admin_signup_notification(
        manager_name=manager_name,
        restaurant_name=restaurant_name,
        email=email,
        whatsapp_number=whatsapp_number,
        card_code=card_code
    )
    
    if email_success:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BetaSignup).where(BetaSignup.id == signup_id))
            signup = result.scalar_one_or_none()
            if signup:
                signup.confirmation_sent = True
                await db.commit()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.post("/beta-signup", status_code=status.HTTP_201_CREATED, dependencies=[Depends(check_rate_limit)])
async def beta_signup(req: BetaSignupRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
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
    new_signup = BetaSignup(
        card_id=card.id,
        manager_name=req.manager_name,
        restaurant_name=req.restaurant_name,
        email=req.email,
        whatsapp_number=req.whatsapp_number,
        locale=req.locale
    )
    db.add(new_signup)

    # 5. Update BetaCard status
    card.status = BetaCardStatus.CLAIMED
    card.claimed_at = datetime.utcnow()
    
    # 6. Save changes to DB first so signup is immediately recorded
    await db.commit()
    await db.refresh(new_signup)
    
    # 7. Offload email dispatch to BackgroundTasks so the API returns instantly
    # and doesn't get blocked by slow SMTP connection / timeouts.
    background_tasks.add_task(
        send_signup_emails_task,
        signup_id=new_signup.id,
        manager_name=req.manager_name,
        restaurant_name=req.restaurant_name,
        email=req.email,
        whatsapp_number=req.whatsapp_number,
        card_code=req.card_code,
        locale=req.locale
    )
        
    return {"message": "Signup successful"}
