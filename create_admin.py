#!/usr/bin/env python3
"""
Standalone script to create admin user.
Run this locally while the Docker containers are running.
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
    database_url = os.getenv('DATABASE_URL', 'postgresql+asyncpg://postgres:password123@localhost:5432/whatsapp_food')

    engine = create_async_engine(database_url, echo=True)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if admin user already exists
        result = await db.execute(select(User).where(User.email == "admin@geqo.com"))
        admin_user = result.scalar_one_or_none()

        if admin_user:
            print("ℹ️ Admin user already exists: admin@geqo.com / admin123")
            return

        # Create initial admin user
        admin_user = User(
            email="admin@geqo.com",
            password_hash=get_password_hash("admin123"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin_user)
        await db.commit()

        print("✅ Admin user created successfully!")
        print("📧 Email: admin@geqo.com")
        print("🔑 Password: admin123")

if __name__ == "__main__":
    asyncio.run(create_admin())