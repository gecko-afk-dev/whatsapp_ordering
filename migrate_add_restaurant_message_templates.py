"""
migrate_add_restaurant_message_templates.py — WhatsApp order-lifecycle templates

Creates the restaurant_message_templates table and guarantees restaurants.waba_id
exists.

Backs POST /api/v1/admin/restaurant/{id}/provision-templates and
GET /api/v1/admin/restaurant/message-templates (app/api/admin.py).

Standalone migration script (mirrors migrate_add_data_deletion_requests.py and
migrate_add_event_log.py, the patterns already used in this repo). Safe to run
multiple times — uses IF NOT EXISTS guards throughout.

Note on `waba_id`: migrate_add_subscription_tier.py already added this column,
but it is re-asserted here (IF NOT EXISTS) so a database provisioned before that
script, or from Base.metadata.create_all, still ends up correct. It is the Meta
WhatsApp Business Account ID and is DISTINCT from phone_number_id — the WABA
owns the message-template catalog, the phone number ID sends messages.

Note on `meta_status`: stored as plain VARCHAR + CHECK constraint (not a native
Postgres ENUM), matching this repo's precedent for restaurants.subscription_tier
and data_deletion_requests.status. The model column is declared with
native_enum=False for the same reason.

Usage:
    python3 migrate_add_restaurant_message_templates.py
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

    try:
        async with engine.begin() as conn:
            logger.info("Step 1/3 — Ensuring restaurants.waba_id exists…")
            await conn.execute(text(
                "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS waba_id VARCHAR(64);"
            ))

            logger.info("Step 2/3 — Creating table 'restaurant_message_templates' (IF NOT EXISTS)…")
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS restaurant_message_templates (
                    id               SERIAL PRIMARY KEY,
                    restaurant_id    INTEGER      NOT NULL REFERENCES restaurants(id),
                    template_key     VARCHAR(64)  NOT NULL,
                    meta_status      VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                                     CHECK (meta_status IN ('PENDING', 'APPROVED', 'REJECTED')),
                    meta_template_id VARCHAR(64),
                    submitted_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
                    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_restaurant_template_key UNIQUE (restaurant_id, template_key)
                );
            """))

            logger.info("Step 3/3 — Creating indexes (IF NOT EXISTS)…")
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_restaurant_message_templates_restaurant_id "
                "ON restaurant_message_templates (restaurant_id);",
                "CREATE INDEX IF NOT EXISTS ix_restaurant_message_templates_template_key "
                "ON restaurant_message_templates (template_key);",
                "CREATE INDEX IF NOT EXISTS ix_restaurant_message_templates_meta_status "
                "ON restaurant_message_templates (meta_status);",
            ):
                await conn.execute(text(stmt))

        logger.info("✅ Migration successful: restaurant_message_templates ready.")
    except Exception as exc:
        logger.error("❌ Migration failed: %s", exc)
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
