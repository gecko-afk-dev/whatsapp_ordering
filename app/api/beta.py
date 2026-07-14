from fastapi import APIRouter, HTTPException, Request, Depends, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Tuple
from datetime import datetime
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
RATE_LIMIT_MAX_REQUESTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60

async def check_rate_limit(request: Request):
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
    
    # 6 & 7. Send Emails (we commit first to ensure we don't send emails if DB fails)
    await db.commit()
    
    # Fire confirmation email to user
    email_success = await EmailService.send_beta_confirmation(
        email=req.email,
        manager_name=req.manager_name,
        restaurant_name=req.restaurant_name,
        locale=req.locale
    )
    
    # Fire notification email to admin
    await EmailService.send_admin_signup_notification(
        manager_name=req.manager_name,
        restaurant_name=req.restaurant_name,
        email=req.email,
        whatsapp_number=req.whatsapp_number,
        card_code=req.card_code
    )
    
    # If user email sent successfully, update tracking flag
    if email_success:
        new_signup.confirmation_sent = True
        await db.commit()
        
    return {"message": "Signup successful"}
