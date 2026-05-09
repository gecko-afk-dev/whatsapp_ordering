# GEQO WhatsApp Ordering System

A SaaS platform that enables restaurants to accept food orders via WhatsApp, with a real-time admin dashboard.

## Features

- **WhatsApp Integration** — Menu browsing, cart management, and order placement via WhatsApp Flows
- **Trilingual Support** — French, Arabic (Darija), and English
- **Admin Dashboard** — Vue.js PWA for managing restaurants, orders, and analytics
- **Real-time Updates** — WebSocket-powered live order feed for restaurant dashboards
- **Multi-tenant** — Each restaurant has its own WhatsApp number, menu, and order stream
- **Modifier & Exclusion System** — Customers can customize items (e.g., extra cheese, no onions)
- **Delivery & Pickup** — Location sharing for delivery orders
- **Role-based Access** — Admin and restaurant owner roles with JWT authentication

## Tech Stack

- **Backend:** FastAPI (async), SQLAlchemy 2.0 (async), PostgreSQL
- **Frontend:** Vue.js 3, Tailwind CSS (PWA)
- **Messaging:** WhatsApp Cloud API (Meta)
- **Infrastructure:** Docker Compose, Caddy (HTTPS reverse proxy)

## Quick Start

### Prerequisites

- Docker & Docker Compose
- A Meta WhatsApp Business API account with:
  - A permanent System User token
  - A registered phone number
  - A WhatsApp Flow ID
  - An App Secret

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

Required variables:
| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (auto-set by Docker Compose) |
| `SECRET_KEY` | JWT signing key — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `WHATSAPP_API_TOKEN` | Meta permanent System User token |
| `PHONE_NUMBER_ID` | WhatsApp phone number ID from Meta |
| `WHATSAPP_FLOW_ID` | WhatsApp Flow ID |
| `WHATSAPP_APP_SECRET` | App Secret from Meta Developer Dashboard |
| `WHATSAPP_VERIFY_TOKEN` | Custom token for webhook verification |

### 2. Update Caddyfile

Replace `yourdomain.com` in `Caddyfile` with your actual domain.

### 3. Generate Encryption Keys

```bash
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

### 4. Start the Application

```bash
docker compose up -d --build
```

### 5. Create Admin User

Visit `https://yourdomain.com/static/setup.html` or run:

```bash
docker compose exec app python -m app.seed_admin
```

### 6. Seed Test Data (Optional)

```bash
docker compose exec app python -m app.seed_trilingual
```

### 7. Access the Dashboard

Visit `https://yourdomain.com/static/index.html` and log in with the admin credentials.

## Project Structure

```
app/
  main.py              # FastAPI app, router registration, lifespan
  models.py            # SQLAlchemy models (16 tables)
  api/
    webhook.py         # WhatsApp webhook (verification + message handling)
    flow_handler.py    # WhatsApp Flow data exchange (encrypted)
    dashboard.py       # Restaurant dashboard (WebSocket + REST)
    admin.py           # Admin portal (analytics, restaurant CRUD, auth)
  core/
    config.py          # Pydantic settings (env validation)
    database.py        # Async SQLAlchemy engine & session
    auth.py            # JWT auth, password hashing, role guards
  services/
    whatsapp.py        # WhatsApp Cloud API client
    order_service.py   # Order processing logic
    socket_manager.py  # WebSocket connection manager
  seed_admin.py        # Admin user seeder
  seed_trilingual.py   # Test restaurant + menu seeder
static/
  index.html           # Admin dashboard (Vue.js PWA)
  setup.html           # First-time admin setup page
Dockerfile
docker-compose.yml
Caddyfile
```

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | None | Health check |
| `GET` | `/api/v1/webhook` | None | WhatsApp webhook verification |
| `POST` | `/api/v1/webhook` | Signature | WhatsApp message handler |
| `POST` | `/api/v1/flow/flow-endpoint` | Encrypted | WhatsApp Flow data exchange |
| `POST` | `/api/v1/admin/login` | None | JWT login |
| `POST` | `/api/v1/admin/setup-admin` | None | First-time admin creation |
| `GET` | `/api/v1/admin/analytics/summary` | Admin | Business analytics |
| `GET` | `/api/v1/admin/restaurants` | Admin | List restaurants |
| `POST` | `/api/v1/admin/restaurants` | Admin | Create restaurant |
| `WS` | `/api/v1/dashboard/ws/{id}` | JWT | Live order feed |
| `GET` | `/api/v1/dashboard/orders/{id}` | JWT | Active orders |
| `POST` | `/api/v1/dashboard/orders/{id}/status` | JWT | Update order status |

## Development (Without Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL locally, then:
uvicorn app.main:app --reload
```
