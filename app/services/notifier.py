"""
Notification service module.

Handles sending alerts via Telegram with proper error handling
and response validation.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            logger.info(f"Telegram response: {response.status_code} {response.text}")
            response.raise_for_status()
            return True
    except httpx.HTTPError as e:
        logger.error(f"Telegram failed: {e}")
        return False


async def validate_telegram_token() -> bool:
    """
    Validate Telegram bot token by calling getMe endpoint.

    Returns:
        True if token is valid, False otherwise.
    """
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("ok") is True
    except Exception as e:
        logger.error(f"Telegram token validation failed: {e}")
        return False
