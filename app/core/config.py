from typing import Optional

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

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
    DRIVER_FLOW_ID: str  # Flow ID for the Driver PIN Verification Flow
    WHATSAPP_APP_SECRET: str
    SECRET_KEY: str
    ALLOWED_ORIGINS: str = ""  # Default empty; must be set in production
    REDIS_URL: Optional[str] = "redis://redis:6379/0"

    # Resend Configuration
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None
    ADMIN_NOTIFICATION_EMAIL: str = "admin@mygeqo.com"

    # Feature Flags for incremental release
    FEATURE_OVERVIEW_ENABLED: bool = False
    FEATURE_STAFF_ENABLED: bool = False
    FEATURE_DRIVERS_ENABLED: bool = False
    FEATURE_AUDIT_LOGS_ENABLED: bool = False

    # Cookie security — set COOKIE_SECURE=false in local HTTP dev environments.
    # Production must always keep COOKIE_SECURE=true.
    # COOKIE_SAMESITE="lax" is required when the frontend and API are on separate
    # subdomains (app.mygeqo.com <-> api.mygeqo.com).
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def redis_url_formatted(self) -> str:
        url = self.REDIS_URL or "redis://redis:6379/0"
        if not url.startswith(("redis://", "rediss://", "unix://")):
            url = f"redis://{url}"
        return url

# Create one "settings" object to be used everywhere
settings = Settings()