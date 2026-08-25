"""
migrate_remove_commission_rate.py — Drop the vestigial commission_rate column

Standalone migration script (mirrors migrate_add_subscription_tier.py, migrate_add_event_log.py patterns).
Safe to run multiple times — uses IF EXISTS guard.

GEQO's pricing model is 0% commission + a flat 3.00 MAD micro-toll per order;
commission_rate was never read by any pricing/order-total logic and is dead schema.

Usage:
    cd /Users/hamzamoustaati/Whatsapp-oredering-repo/whatsapp_ordering
    python3 migrate_remove_commission_rate.py
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
        logger.info("Step 1/2 — Dropping column 'restaurants.commission_rate' (IF EXISTS)…")
        await conn.execute(text("""
            ALTER TABLE restaurants DROP COLUMN IF EXISTS commission_rate;
        """))

        logger.info("Step 2/2 — Verifying column no longer exists…")
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'restaurants' AND column_name = 'commission_rate';
        """))
        count = result.scalar()
        if count == 0:
            logger.info("✅ Migration complete. restaurants.commission_rate has been removed.")
        else:
            logger.error("❌ Column still present after migration — check PostgreSQL permissions.")
            sys.exit(1)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
