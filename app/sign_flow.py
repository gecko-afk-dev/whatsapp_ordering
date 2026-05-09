import logging
import os
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

async def sign_flow():
    """Signs the WhatsApp Flow by uploading the public key using Multipart Form-Data."""
    pub_key_path = "public.pem"
    
    if not os.path.exists(pub_key_path):
        logger.error("Public key not found: %s", pub_key_path)
        return

    with open(pub_key_path, "r") as f:
        public_key_content = f.read().strip()

    # Correct endpoint: /PHONE_NUMBER_ID/whatsapp_business_encryption (NOT flow ID!)
    phone_number_id = settings.PHONE_NUMBER_ID
    url = f"https://graph.facebook.com/v25.0/{phone_number_id}/whatsapp_business_encryption"
    
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # Correct parameter name: business_public_key (NOT public_key)
    data = {
        "business_public_key": public_key_content
    }

    logger.info("Uploading WhatsApp public key for phone number ID %s", phone_number_id)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, data=data)
            logger.info("Meta response status: %s", response.status_code)

            try:
                result = response.json()
                logger.info("Meta response body: %s", result)
            except ValueError:
                logger.info("Meta response body: %s", response.text)

            if response.status_code == 200:
                logger.info("Success: Meta accepted the public key.")
            else:
                logger.error("Failed to upload public key to Meta.")
        except Exception:
            logger.exception("Connection error while uploading public key")

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(sign_flow())