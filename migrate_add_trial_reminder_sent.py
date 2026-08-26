"""
migrate_add_trial_reminder_sent.py — Add beta_signups.trial_reminder_sent

Backs send_trial_reminders.py's dedup guard (so the daily cron never sends
the "3 days left" WhatsApp nudge twice for the same signup). IF NOT EXISTS
guarded, safe to re-run — same pattern as the other standalone migration
scripts in this repo.

Usage:
    python3 migrate_add_trial_reminder_sent.py
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_migration():
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        logger.info("Step 1/2 — beta_signups.trial_reminder_sent (IF NOT EXISTS, default false)…")
        await conn.execute(text("""
            ALTER TABLE beta_signups
            ADD COLUMN IF NOT EXISTS trial_reminder_sent BOOLEAN NOT NULL DEFAULT FALSE;
        """))

        logger.info("Step 2/2 — Verifying column exists…")
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'beta_signups' AND column_name = 'trial_reminder_sent';
        """))
        count = result.scalar()
        if count == 1:
            logger.info("✅ Migration complete. beta_signups.trial_reminder_sent is ready.")
        else:
            logger.error("❌ Column not found after migration — check PostgreSQL permissions.")
            sys.exit(1)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
