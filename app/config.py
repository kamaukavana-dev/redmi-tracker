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
        LOW_BATTERY_THRESHOLD: Battery percentage threshold for low battery alerts (default: 15)
        OFFLINE_THRESHOLD_MINUTES: Minutes without update to consider device offline (default: 60)
        TELEGRAM_RETRY_COUNT: Number of retry attempts for Telegram notifications (default: 3)
        TELEGRAM_RETRY_DELAY: Base delay between retries in seconds (default: 2)
        DEVICE_NAME: Human-readable device name for alerts (default: "Redmi 14C")
        GPS_STALE_THRESHOLD_MINUTES: Minutes without GPS update to consider GPS stale (default: 30)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Required
    database_url: str
    api_key: str
    telegram_bot_token: str
    telegram_chat_id: str

    # Logging
    log_level: str = "INFO"

    # Rate limiting
    rate_limit_per_minute: int = 20

    # Geofencing
    geofence_cooldown_minutes: int = 30

    # Device monitoring
    low_battery_threshold: int = 15
    offline_threshold_minutes: int = 60
    gps_stale_threshold_minutes: int = 30

    # Independent cooldown for health alerts (LOW_BATTERY, GPS_SIGNAL_LOST,
    # DEVICE_OFFLINE). Enforced to a minimum of 30 minutes in code.
    health_alert_cooldown_minutes: int = 30

    # Location is considered too stale for geofence evaluation past this age.
    location_staleness_threshold_minutes: int = 10

    # Telegram
    telegram_retry_count: int = 3
    telegram_retry_delay: int = 2

    # Device identity
    device_name: str = "Redmi 14C"

    # Startup
    strict_startup_validation: bool = False


settings = Settings()