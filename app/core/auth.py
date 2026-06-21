from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models import User, UserRole

# Security settings — read from .env via settings, no insecure fallback
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Get current authenticated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            raise credentials_exception
        return user

async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Get current user and ensure they are admin."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

async def get_current_restaurant_owner(current_user: User = Depends(get_current_user)) -> User:
    """Get current user and ensure they are restaurant owner."""
    if current_user.role != UserRole.RESTAURANT_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

async def get_manager_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """Get current user and ensure they are admin or restaurant owner."""
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

async def get_current_cashier_or_above(current_user: User = Depends(get_current_user)) -> User:
    """Allows RESTAURANT_OWNER and CASHIER (covers order mgmt + driver dispatch)."""
    if current_user.role not in [UserRole.ADMIN, UserRole.RESTAURANT_OWNER, UserRole.CASHIER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

async def get_current_kitchen_or_above(current_user: User = Depends(get_current_user)) -> User:
    """Allows RESTAURANT_OWNER, CASHIER, and KITCHEN_STAFF (read access to orders)."""
    if current_user.role not in [
        UserRole.ADMIN, UserRole.RESTAURANT_OWNER,
        UserRole.CASHIER, UserRole.KITCHEN_STAFF
    ]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

def assert_restaurant_access(current_user: User, restaurant_id: int) -> None:
    """
    Verify that a non-admin user belongs to the requested restaurant.
    Raises HTTP 403 on tenant boundary violation.
    """
    if current_user.role == UserRole.ADMIN:
        return  # admins can access any restaurant
    if current_user.restaurant_id != restaurant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this restaurant"
        )