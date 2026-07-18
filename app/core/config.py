from typing import Optional

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

    # SMTP Configuration (kept for compatibility, but unused by Resend)
    SMTP_HOST: str = "smtp.larksuite.com"
    SMTP_PORT: int = 465
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_SENDER_NAME: str = "GEQO"

    # Resend Configuration
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None
    ADMIN_NOTIFICATION_EMAIL: str = "admin@geqo.com"

    # Feature Flags for incremental release
    FEATURE_OVERVIEW_ENABLED: bool = False
    FEATURE_STAFF_ENABLED: bool = False
    FEATURE_DRIVERS_ENABLED: bool = False
    FEATURE_AUDIT_LOGS_ENABLED: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Create one "settings" object to be used everywhere
settings = Settings()