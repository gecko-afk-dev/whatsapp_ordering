"""
migrate_add_event_log.py — Phase A: Create raw_l1 schema and event_logs table

Standalone migration script (mirrors migrate_add_slug.py, migrate_roles.py patterns).
Safe to run multiple times — uses IF NOT EXISTS and IF NOT EXISTS guards.

Usage:
    cd /Users/hamzamoustaati/Whatsapp-oredering-repo/whatsapp_ordering
    python3 migrate_add_event_log.py
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
        logger.info("Step 1/4 — Creating schema 'raw_l1' (IF NOT EXISTS)…")
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw_l1;"))

        logger.info("Step 2/4 — Creating table 'raw_l1.event_logs' (IF NOT EXISTS)…")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS raw_l1.event_logs (
                id            VARCHAR(36)  PRIMARY KEY,
                event_id      VARCHAR(64)  UNIQUE,
                event_type    VARCHAR(60)  NOT NULL,
                restaurant_id INTEGER,
                customer_hash VARCHAR(64),
                channel       VARCHAR(20)  NOT NULL,
                payload       JSONB,
                timestamp     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            );
        """))

        logger.info("Step 3/4 — Creating indexes…")
        index_stmts = [
            # Fast lookup by event_type for funnel queries
            """
            CREATE INDEX IF NOT EXISTS ix_event_logs_event_type
            ON raw_l1.event_logs (event_type);
            """,
            # Tenant-scoped analytics queries
            """
            CREATE INDEX IF NOT EXISTS ix_event_logs_restaurant_id
            ON raw_l1.event_logs (restaurant_id);
            """,
            # Time-series / window queries
            """
            CREATE INDEX IF NOT EXISTS ix_event_logs_timestamp
            ON raw_l1.event_logs (timestamp DESC);
            """,
            # Customer funnel reconstruction (pseudonymized)
            """
            CREATE INDEX IF NOT EXISTS ix_event_logs_customer_hash
            ON raw_l1.event_logs (customer_hash)
            WHERE customer_hash IS NOT NULL;
            """,
            # Composite: per-restaurant time-series (most common analytics pattern)
            """
            CREATE INDEX IF NOT EXISTS ix_event_logs_restaurant_timestamp
            ON raw_l1.event_logs (restaurant_id, timestamp DESC);
            """,
        ]
        for stmt in index_stmts:
            await conn.execute(text(stmt.strip()))

        logger.info("Step 4/4 — Verifying table exists…")
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'raw_l1' AND table_name = 'event_logs';
        """))
        count = result.scalar()
        if count == 1:
            logger.info("✅ Migration complete. raw_l1.event_logs is ready.")
        else:
            logger.error("❌ Table not found after migration — check PostgreSQL permissions.")
            sys.exit(1)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
