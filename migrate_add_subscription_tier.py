import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings

async def run_migration():
    engine = create_async_engine(settings.DATABASE_URL)
    sql = """
    ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(20) DEFAULT 'STARTER';
    ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS waba_id VARCHAR(64);
    ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS phone_number_id VARCHAR(64);
    ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS whatsapp_access_token TEXT;
    ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS whatsapp_status VARCHAR(30) DEFAULT 'DISCONNECTED';
    ALTER TABLE customers ADD COLUMN IF NOT EXISTS ctwa_free_window_expires_at TIMESTAMP WITH TIME ZONE;
    ALTER TABLE customers ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN DEFAULT FALSE;
    """
    
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
        print("✅ Migration successful: Added subscription_tier and Meta WABA columns.")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_migration())
