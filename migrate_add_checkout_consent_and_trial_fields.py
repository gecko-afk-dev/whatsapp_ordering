"""
migrate_add_checkout_consent_and_trial_fields.py — Checkout consent + beta trial length

Backs three independent additions, bundled into one script since they're all
small, additive, IF-NOT-EXISTS-guarded column adds (mirrors migrate_add_event_log.py,
migrate_roles.py patterns already used in this repo):

1. customers.marketing_opt_in — CNDP-compliant opt-in checkbox at PWA checkout,
   independent of DataDeletionRequest. NOTE: this column may already exist in
   production from migrate_add_subscription_tier.py's ALTER TABLE, which added
   it but was never matched by a model field until now — this script's guard
   makes it safe to run either way.

2. orders.terms_accepted_at — per-order Terms of Service acceptance timestamp
   (app/api/public_orders.py — checkout now requires terms_accepted=true).

3. beta_cards.trial_days (default 14) and beta_signups.trial_ends_at — lets
   specific hand-pitched MVP-launch cards be set to a 30-day trial before
   being handed out, while publicly-claimed cards default to 14.

Usage:
    python3 migrate_add_checkout_consent_and_trial_fields.py
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
        logger.info("Step 1/5 — customers.marketing_opt_in (IF NOT EXISTS)…")
        await conn.execute(text("""
            ALTER TABLE customers
            ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE;
        """))

        logger.info("Step 2/5 — orders.terms_accepted_at (IF NOT EXISTS)…")
        await conn.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP;
        """))

        logger.info("Step 3/5 — beta_cards.trial_days (IF NOT EXISTS, default 14)…")
        await conn.execute(text("""
            ALTER TABLE beta_cards
            ADD COLUMN IF NOT EXISTS trial_days INTEGER NOT NULL DEFAULT 14;
        """))

        logger.info("Step 4/5 — beta_signups.trial_ends_at (IF NOT EXISTS)…")
        await conn.execute(text("""
            ALTER TABLE beta_signups
            ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP;
        """))

        logger.info("Step 5/5 — Verifying all four columns exist…")
        result = await conn.execute(text("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE (table_name = 'customers' AND column_name = 'marketing_opt_in')
               OR (table_name = 'orders' AND column_name = 'terms_accepted_at')
               OR (table_name = 'beta_cards' AND column_name = 'trial_days')
               OR (table_name = 'beta_signups' AND column_name = 'trial_ends_at');
        """))
        rows = result.fetchall()
        if len(rows) == 4:
            logger.info("✅ Migration complete. All 4 columns verified: %s", [f"{r[0]}.{r[1]}" for r in rows])
        else:
            found = {f"{r[0]}.{r[1]}" for r in rows}
            expected = {"customers.marketing_opt_in", "orders.terms_accepted_at", "beta_cards.trial_days", "beta_signups.trial_ends_at"}
            logger.error("❌ Missing columns after migration: %s", expected - found)
            sys.exit(1)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
