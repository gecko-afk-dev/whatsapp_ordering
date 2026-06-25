from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    """
    This class automatically reads your .env file.
    If a variable is missing, the app will refuse to start (Fail-Fast behavior).
    """
    DATABASE_URL: str
    WHATSAPP_API_TOKEN: str
    PHONE_NUMBER_ID: str
    WHATSAPP_VERIFY_TOKEN: str
    WHATSAPP_FLOW_ID: str
    WHATSAPP_APP_SECRET: str
    SECRET_KEY: str
    ALLOWED_ORIGINS: str = ""  # Default empty; must be set in production

    # SMTP Configuration (Lark Suite)
    SMTP_HOST: str = "smtp.larksuite.com"
    SMTP_PORT: int = 465
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_SENDER_NAME: str = "GEQO"
    ADMIN_NOTIFICATION_EMAIL: str = "admin@geqo.com"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Create one "settings" object to be used everywhere
settings = Settings()