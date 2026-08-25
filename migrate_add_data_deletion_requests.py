"""
migrate_add_data_deletion_requests.py — Create the data_deletion_requests table

Backs POST /api/v1/public/data-deletion-request (app/api/compliance.py).
Standalone migration script (mirrors migrate_add_event_log.py, migrate_roles.py
patterns already used in this repo). Safe to run multiple times — uses
IF NOT EXISTS guards throughout.

Note on `status`: stored as plain VARCHAR + CHECK constraint (not a native
Postgres ENUM type), matching this repo's existing precedent for
`restaurants.subscription_tier` (see migrate_add_subscription_tier.py) rather
than the ALTER-TYPE-based pattern used for `userrole`. The model column is
declared with native_enum=False for the same reason — one less CREATE
TYPE/ALTER TYPE dependency to manage for a two-value status field.

Usage:
    python3 migrate_add_data_deletion_requests.py
"""
import asyncio
import logging
import os
import sys

# Allow imports from the app package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_migration():
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        logger.info("Step 1/3 — Creating table 'data_deletion_requests' (IF NOT EXISTS)…")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS data_deletion_requests (
                id            SERIAL PRIMARY KEY,
                phone_number  VARCHAR(20)  NOT NULL,
                reason        TEXT,
                status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING', 'COMPLETED')),
                requested_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
                resolved_at   TIMESTAMP,
                admin_notes   TEXT
            );
        """))

        logger.info("Step 2/3 — Creating indexes…")
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_data_deletion_requests_phone_number
            ON data_deletion_requests (phone_number);
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_data_deletion_requests_status
            ON data_deletion_requests (status);
        """))

        logger.info("Step 3/3 — Verifying table exists…")
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'data_deletion_requests';
        """))
        count = result.scalar()
        if count == 1:
            logger.info("✅ Migration complete. data_deletion_requests is ready.")
        else:
            logger.error("❌ Table not found after migration — check PostgreSQL permissions.")
            sys.exit(1)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
