import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.database import engine
from app.models import Base
from app.api import webhook, dashboard, flow_handler, admin

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

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS for PWA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your domains
    allow_credentials=True,
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


@app.get("/")
def home():
    return {"status": "Engine Online", "version": "1.4 - Admin Dashboard Phase 1"}
