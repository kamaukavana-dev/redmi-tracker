"""
Application configuration module.

Provides Settings class for loading and validating environment variables.
All required environment variables must be set before application startup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Required environment variables:
        DATABASE_URL: PostgreSQL connection string
        API_KEY: Secret key for API authentication
        TELEGRAM_BOT_TOKEN: Telegram bot token for alerts
        TELEGRAM_CHAT_ID: Telegram chat ID to receive alerts

    Optional environment variables:
        LOG_LEVEL: Logging level (default: INFO)
        RATE_LIMIT_PER_MINUTE: Max requests per minute per API key (default: 20)
        GEOFENCE_COOLDOWN_MINUTES: Cooldown between geofence alerts (default: 30)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str
    api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    log_level: str = "INFO"
    rate_limit_per_minute: int = 20
    geofence_cooldown_minutes: int = 30
    strict_startup_validation: bool = False


settings = Settings()
