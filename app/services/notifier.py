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
    """
    Send a message to Telegram chat.

    Args:
        message: HTML-formatted message text to send.

    Returns:
        True if message was sent successfully, False otherwise.
    """
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("ok") is True:
                return True
            else:
                logger.warning(f"Telegram API returned error: {data}")
                return False

    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram HTTP error: {e.response.status_code} - {e.response.text}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Telegram request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending Telegram message: {e}")
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