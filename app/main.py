import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.database import engine
from app.core.config import settings
from app.models import Base
from app.api import webhook, dashboard, flow_handler, admin, menu, drivers, auth, beta

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.handlers = [handler]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # NOTE: Database schema creation disabled. Use Alembic migrations instead.
    # To apply pending migrations, run: alembic upgrade head
    # Uncomment the line below only for development if no migrations are available:
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="GEQO WhatsApp SaaS Engine", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logging.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )

# CORS for Frontend — only allow explicit origins, reject wildcards
origins = []
if settings.ALLOWED_ORIGINS and settings.ALLOWED_ORIGINS.strip():
    origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]

# Reject wildcard origins in production-like setups
if "*" in origins:
    logger.warning("WARNING: Wildcard CORS origin detected. This is insecure in production.")

allow_credentials = len(origins) > 0 and "*" not in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["http://localhost:3000"],  # Safe fallback
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
    return response

# 1. WhatsApp Webhook (Handshake & Message Router)
app.include_router(webhook.router, prefix="/api/v1")

# 2. Restaurant Dashboard (WebSockets & Order Management)
app.include_router(dashboard.router, prefix="/api/v1/dashboard")

# 3. WhatsApp Flow Dynamic Endpoint (The Mini-App Logic)
app.include_router(flow_handler.router, prefix="/api/v1/flow")

# 4. Admin Dashboard (Unified portal for admins and restaurant owners)
app.include_router(admin.router, prefix="/api/v1/admin")

# 5. Menu Management
app.include_router(menu.router, prefix="/api/v1/admin/menu")

# 6. Driver Management
app.include_router(drivers.router, prefix="/api/v1/admin/drivers")

# 7. Authentication
app.include_router(auth.router, prefix="/api/v1/auth")

# 8. Public Beta Signup (No auth required)
app.include_router(beta.router, prefix="/api/v1/public")

@app.get("/")
def home():
    return {"status": "Engine Online", "version": "1.5 - Menu Management Phase"}
