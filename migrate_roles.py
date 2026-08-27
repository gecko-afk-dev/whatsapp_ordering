#!/usr/bin/env python3
"""
One-time migration script to add new UserRole enum values to PostgreSQL.
SQLAlchemy's create_all() cannot modify existing enum types, so this must
be run manually once before deploying the updated application code.

Usage:
    docker compose exec app python migrate_roles.py
    # OR locally:
    python3 migrate_roles.py
"""

import asyncio
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL environment variable is required.")
    print("   Refusing to fall back to a hardcoded default credential.")
    sys.exit(1)

NEW_ROLES = ["cashier", "kitchen_staff"]


async def migrate():
    engine = create_async_engine(DATABASE_URL, echo=True)

    async with engine.begin() as conn:
        for role in NEW_ROLES:
            try:
                # IF NOT EXISTS is only supported in PG 9.6+
                await conn.execute(
                    text(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{role}'")
                )
                print(f"✅ Added role: {role}")
            except Exception as e:
                print(f"⚠️  Could not add role '{role}': {e}")

        # Also ensure the new audit_logs table and any other new tables are created
        from app.models import Base
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Schema sync complete (new tables created if missing)")

    await engine.dispose()
    print("\n🎉 Migration complete. You can now restart the application.")


if __name__ == "__main__":
    asyncio.run(migrate())
