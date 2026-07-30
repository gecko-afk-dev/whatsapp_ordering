from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Create the "Engine"
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,   # Detects stale connections before use (handles Neon idle drops)
    pool_recycle=300,     # Recycle connections every 5 min to stay ahead of Neon's timeout
)

# Create the "Session Factory"
AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)