from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api import webhook, dashboard, flow_handler, admin, menu, drivers, auth, beta, public_menu, public_orders, health, compliance
from app.core.logging_config import setup_logging

logger = setup_logging()


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
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Our engineering team has been notified."},
    )

origins = [
    "https://mygeqo.com",
    "https://www.mygeqo.com",
    "https://app.mygeqo.com",
    "https://menu.mygeqo.com",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.mygeqo\.com", # Dynamically matches all *.mygeqo.com subdomains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

# 9. Public PWA Menu & Orders
app.include_router(public_menu.router, prefix="/api/v1/public")
app.include_router(public_orders.router, prefix="/api/v1/public")

# 9b. Public Compliance (CNDP data-deletion requests)
app.include_router(compliance.router, prefix="/api/v1/public")

# 10. Health Check (available at both root and /api/v1/health)
app.include_router(health.router)
app.include_router(health.router, prefix="/api/v1")

@app.get("/")
def home():
    return {"status": "Engine Online", "version": "1.5 - Infrastructure Phase"}
