#!/usr/bin/env python3
"""
Standalone script to create admin user.
Requires INITIAL_ADMIN_PASSWORD environment variable.

Usage:
  export INITIAL_ADMIN_PASSWORD=secure_password_here
  python create_admin.py
"""

import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

import sys
sys.path.append('.')

from app.models import Base, User, UserRole
from app.core.auth import get_password_hash

async def create_admin():
    database_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://postgres:password123@db:5432/whatsapp_food')

    engine = create_async_engine(database_url, echo=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if admin user already exists
        result = await db.execute(select(User).where(User.email == "admin@geqo.com"))
        admin_user = result.scalar_one_or_none()

        if admin_user:
            print("ℹ️ Admin user already exists: admin@geqo.com")
            return

        # Require password via environment variable
        initial_admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")
        if not initial_admin_password:
            print("❌ INITIAL_ADMIN_PASSWORD environment variable is required.")
            print("   Usage: INITIAL_ADMIN_PASSWORD=<secure-password> python create_admin.py")
            return

        # Create initial admin user
        admin_user = User(
            email="admin@geqo.com",
            password_hash=get_password_hash(initial_admin_password),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin_user)
        await db.commit()

        print("✅ Admin user created successfully!")
        print("📧 Email: admin@geqo.com")
        print("🔑 Password: (set via INITIAL_ADMIN_PASSWORD env var)")

if __name__ == "__main__":
    asyncio.run(create_admin())