from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.future import select
from datetime import datetime, timedelta
import secrets
import re

from app.core.database import AsyncSessionLocal
from app.models import User
from app.services.email import EmailService
from app.core.auth import get_password_hash, get_current_user


def validate_password_strength(password: str) -> None:
    """
    Enforce minimum password strength rules across all password-setting endpoints.
    Raises HTTPException(400) if the password does not meet requirements.
    Rules: min 8 chars, ≥1 digit, ≥1 uppercase letter, ≥1 special character.
    """
    if (
        len(password) < 8
        or not re.search(r"\d", password)
        or not re.search(r"[A-Z]", password)
        or not re.search(r'[!@#$%^&*(),.?":{}|<>]', password)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Password does not meet strength requirements "
                "(minimum 8 characters, 1 number, 1 uppercase letter, 1 special symbol)."
            ),
        )

router = APIRouter()

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == request.email))
        user = result.scalar_one_or_none()
        
        if not user:
            # We still return success to prevent email enumeration
            return {"message": "If that email is registered, a reset link has been sent."}
            
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        await db.commit()
        
        await EmailService.send_password_reset_email(user.email, token)
        
        return {"message": "If that email is registered, a reset link has been sent."}

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    validate_password_strength(request.new_password)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.reset_token == request.token,
                User.reset_token_expiry > datetime.utcnow()
            )
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired token")
            
        user.password_hash = get_password_hash(request.new_password)
        user.reset_token = None
        user.reset_token_expiry = None
        user.requires_password_change = False
        await db.commit()
        
        return {"message": "Password successfully reset. You can now log in."}

@router.post("/setup-password")
async def setup_password(request: ResetPasswordRequest):
    # Setup is practically identical to reset from the backend perspective
    return await reset_password(request)

class ForceChangeRequest(BaseModel):
    new_password: str

@router.post("/force-change-password")
async def force_change_password(request: ForceChangeRequest, current_user: User = Depends(get_current_user)):
    validate_password_strength(request.new_password)

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.id == current_user.id))
        user = res.scalar_one()
        user.password_hash = get_password_hash(request.new_password)
        user.requires_password_change = False
        await db.commit()
        return {"message": "Password updated successfully"}
