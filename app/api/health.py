from datetime import datetime
import time
import shutil
from fastapi import APIRouter, Response
from app.core.database import AsyncSessionLocal
from sqlalchemy import text
from app.core.config import settings

router = APIRouter()

@router.get("/health")
async def health_check(response: Response):
    """
    Deep Health Probe: Checks DB, Redis, and Disk Space.
    Returns 200 OK if all pass, 503 if critical dependencies fail.
    """
    health_status = "healthy"
    status_code = 200
    
    # 1. Database Check
    db_status = "up"
    db_latency = 0.0
    start = time.perf_counter()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        db_latency = round((time.perf_counter() - start) * 1000, 2)
    except Exception as e:
        db_status = "down"
        health_status = "unhealthy"
        status_code = 503
        
    # 2. Redis Check
    redis_status = "down"
    redis_latency = 0.0
    start = time.perf_counter()
    try:
        import redis.asyncio as redis_async
        if settings.REDIS_URL:
            # Short timeout for health probe to prevent hanging
            r = redis_async.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2.0)
            if await r.ping():
                redis_status = "up"
            await r.aclose()
        else:
            redis_status = "skipped"
    except Exception as e:
        health_status = "unhealthy"
        status_code = 503
        
    redis_latency = round((time.perf_counter() - start) * 1000, 2)
    if redis_status == "skipped":
        redis_latency = 0.0

    # 3. Disk Space Check
    disk_status = "ok"
    free_gb = 0.0
    try:
        total, used, free = shutil.disk_usage("/")
        free_gb = round(free / (1024 ** 3), 2)
        if free_gb < 1.0: # Less than 1GB free
            disk_status = "low"
            # We don't fail the healthcheck hard on disk space, but we flag it
    except Exception:
        disk_status = "unknown"

    response.status_code = status_code
    return {
        "status": health_status,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": {
            "database": {"status": db_status, "latency_ms": db_latency},
            "redis": {"status": redis_status, "latency_ms": redis_latency},
            "disk": {"status": disk_status, "free_gb": free_gb}
        }
    }
