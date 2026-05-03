from fastapi import FastAPI
from app.api import webhook

app = FastAPI(title="WhatsApp Ordering System")

# Connect our Webhook
app.include_router(webhook.router, prefix="/api/v1")

@app.get("/")
def home():
    return {"status": "Dockerized FastAPI is running", "message": "Ready for WhatsApp!"}