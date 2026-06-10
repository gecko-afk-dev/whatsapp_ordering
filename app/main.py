import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.database import engine
from app.core.config import settings
from app.models import Base
from app.api import webhook, dashboard, flow_handler, admin, menu, drivers, auth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="GEQO WhatsApp SaaS Engine", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logging.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )

# CORS for Frontend
origins = settings.ALLOWED_ORIGINS.split(",")
allow_credentials = True
if "*" in origins:
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/")
def home():
    return {"status": "Engine Online", "version": "1.5 - Menu Management Phase"}
