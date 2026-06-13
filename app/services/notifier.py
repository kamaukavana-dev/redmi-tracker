"""
Production-grade notification service module.

Handles sending alerts via Telegram with:
- Exponential backoff retry logic
- Graceful error handling
- Request/response validation
- Structured logging for observability
"""

import logging
import asyncio
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramNotificationError(Exception):
    """Custom exception for Telegram notification failures."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


async def send_telegram_with_retry(message: str, max_retries: int = None, base_delay: float = None) -> bool:
    """
    Send Telegram message with exponential backoff retry logic.

    Args:
        message: HTML-formatted message to send
        max_retries: Maximum retry attempts (default: from settings)
        base_delay: Base delay between retries in seconds (default: from settings)

    Returns:
        True if message sent successfully, False otherwise.

    Retry Strategy:
        - Attempt 1: Immediate
        - Attempt 2: After base_delay seconds
        - Attempt 3: After base_delay * 2 seconds
        - Attempt 4: After base_delay * 4 seconds
        - etc.

    Graceful Degradation:
        - All errors are caught and logged
        - Returns False on failure rather than raising
        - Never crashes the calling code
    """
    max_retries = max_retries or settings.telegram_retry_count
    base_delay = base_delay or settings.telegram_retry_delay

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Sending Telegram notification (attempt {attempt + 1}/{max_retries + 1})")

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)

                # Log response for observability
                logger.info(
                    f"Telegram response: status={response.status_code}",
                    extra={
                        "telegram_status": response.status_code,
                        "telegram_body": response.text[:200] if response.text else None,
                    },
                )

                # Check for HTTP errors
                response.raise_for_status()

                # Validate Telegram API response
                data = response.json()
                if data.get("ok") is not True:
                    error_desc = data.get("description", "Unknown error")
                    raise TelegramNotificationError(
                        f"Telegram API returned error: {error_desc}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )

                logger.info("Telegram notification sent successfully")
                return True

        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(f"Telegram request timed out (attempt {attempt + 1}): {e}")

        except httpx.HTTPStatusError as e:
            last_error = TelegramNotificationError(
                f"HTTP error: {e.response.status_code}",
                status_code=e.response.status_code,
                response_body=e.response.text,
            )
            logger.warning(f"Telegram HTTP error (attempt {attempt + 1}): {e.response.status_code}")

        except httpx.HTTPError as e:
            last_error = e
            logger.warning(f"Telegram HTTP error (attempt {attempt + 1}): {e}")

        except TelegramNotificationError as e:
            last_error = e
            logger.warning(f"Telegram API error (attempt {attempt + 1}): {e}")

        except Exception as e:
            last_error = e
            logger.exception(f"Unexpected error sending Telegram (attempt {attempt + 1}): {e}")

        # Wait before retry (exponential backoff)
        if attempt < max_retries:
            delay = base_delay * (2**attempt)
            logger.info(f"Retrying in {delay:.1f} seconds...")
            await asyncio.sleep(delay)

    # All retries exhausted
    logger.error(f"Failed to send Telegram notification after {max_retries + 1} attempts")
    return False


# Backward compatibility alias
send_telegram = send_telegram_with_retry


async def validate_telegram_token() -> bool:
    """
    Validate Telegram bot token by calling getMe endpoint.

    Returns:
        True if token is valid, False otherwise.
    """
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            is_valid = data.get("ok") is True
            if is_valid:
                bot_username = data.get("result", {}).get("username", "unknown")
                logger.info(f"Telegram token validated for bot @{bot_username}")
            else:
                logger.warning(f"Telegram validation failed: {data.get('description', 'Unknown error')}")

            return is_valid

    except httpx.HTTPError as e:
        logger.error(f"Telegram token validation HTTP error: {e}")
        return False
    except Exception as e:
        logger.exception(f"Telegram token validation failed with unexpected error: {e}")
        return False


async def send_health_check() -> bool:
    """
    Send a health check message to verify Telegram connectivity.

    Returns:
        True if health check message sent successfully.
    """
    message = (
        "<b>🟢 Health Check</b>\n\n"
        "Telegram integration is working correctly.\n\n"
        f"Bot: @{settings.telegram_bot_token.split(':')[0]}\n"
        "Status: Operational"
    )

    return await send_telegram_with_retry(message)