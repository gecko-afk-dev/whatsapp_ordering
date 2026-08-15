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
    redis_error = None
    redis_raw = None
    start = time.perf_counter()
    try:
        try:
            import redis.asyncio as aioredis
        except ImportError:
            import aioredis
            
        if settings.redis_url_formatted:
            redis_client = aioredis.from_url(settings.redis_url_formatted)
            pong = await redis_client.ping()
            redis_raw = f"type:{type(pong).__name__}, value:{repr(pong)}"
            
            # Accept any truthy ping response or PONG variant
            if pong is True or pong == "PONG" or pong == b"PONG" or str(pong).upper() == "PONG":
                redis_status = "up"
            else:
                redis_error = f"Unexpected ping response: {redis_raw}"
            await redis_client.aclose()
        else:
            redis_status = "skipped"
    except Exception as e:
        health_status = "unhealthy"
        status_code = 503
        redis_error = f"Exception: {type(e).__name__} - {str(e)}"
        
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
            "redis": {
                "status": redis_status, 
                "latency_ms": redis_latency,
                **({"error": redis_error} if redis_error else {}),
                **({"raw": redis_raw} if redis_raw else {})
            },
            "disk": {"status": disk_status, "free_gb": free_gb}
        }
    }
