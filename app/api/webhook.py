from fastapi import APIRouter, Request, HTTPException, Query, Response

router = APIRouter()

# 1. THE HANDSHAKE (Verification)
@router.get("/webhook")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    # This must match WHATSAPP_VERIFY_TOKEN in your .env
    if mode == "subscribe" and token == "my_secure_token_123":
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token mismatch")

# 2. THE MESSAGE RECEIVER
@router.post("/webhook")
async def handle_events(request: Request):
    payload = await request.json()
    print(f"Received from WhatsApp: {payload}")
    return {"status": "received"}