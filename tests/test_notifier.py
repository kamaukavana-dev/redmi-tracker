"""
Test module for notifier functionality.

Tests Telegram notification service with:
- Exponential backoff retry logic
- Error handling for various failure modes
- Token validation
- Health check functionality
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
import httpx

from app.services.notifier import (
    send_telegram_with_retry,
    validate_telegram_token,
    send_health_check,
    TelegramNotificationError,
)
from app.config import settings


class TestTelegramNotificationError:
    """Tests for TelegramNotificationError exception class."""

    def test_error_with_all_params(self):
        """Error should accept status_code and response_body."""
        error = TelegramNotificationError(
            "Test error",
            status_code=400,
            response_body='{"error": "bad request"}',
        )
        assert str(error) == "Test error"
        assert error.status_code == 400
        assert error.response_body == '{"error": "bad request"}'

    def test_error_with_minimal_params(self):
        """Error should work with just message."""
        error = TelegramNotificationError("Simple error")
        assert str(error) == "Simple error"
        assert error.status_code is None
        assert error.response_body is None


class TestSendTelegramWithRetry:
    """Tests for send_telegram_with_retry function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Should succeed on first attempt and return True."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true, "result": {}}'
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await send_telegram_with_retry("Test message")

        assert result is True
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_after_timeout_retry(self):
        """Should retry after timeout and eventually succeed."""
        mock_success_response = Mock()
        mock_success_response.status_code = 200
        mock_success_response.text = '{"ok": true}'
        mock_success_response.json.return_value = {"ok": True}
        mock_success_response.raise_for_status = Mock()

        timeout_exception = httpx.TimeoutException("Request timed out")

        call_count = 0

        async def mock_post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise timeout_exception
            return mock_success_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post_side_effect)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test message", max_retries=2, base_delay=0.01)

        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_failure_after_all_retries_timeout(self):
        """Should return False after exhausting all retries on timeout."""
        timeout_exception = httpx.TimeoutException("Request timed out")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=timeout_exception)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test message", max_retries=2, base_delay=0.01)

        assert result is False
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_http_status_error_handling(self):
        """Should handle HTTP status errors and retry."""
        mock_error_response = Mock()
        mock_error_response.status_code = 500
        mock_error_response.text = 'Internal Server Error'

        http_error = httpx.HTTPStatusError(
            "Server Error",
            request=Mock(),
            response=mock_error_response,
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test message", max_retries=1, base_delay=0.01)

        assert result is False

    @pytest.mark.asyncio
    async def test_http_error_handling(self):
        """Should handle generic HTTP errors."""
        http_error = httpx.HTTPError("Connection error")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test message", max_retries=1, base_delay=0.01)

        assert result is False

    @pytest.mark.asyncio
    async def test_telegram_api_error_handling(self):
        """Should handle Telegram API errors (ok: false)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": false, "description": "Bot was blocked"}'
        mock_response.json.return_value = {"ok": False, "description": "Bot was blocked"}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test message", max_retries=1, base_delay=0.01)

        assert result is False

    @pytest.mark.asyncio
    async def test_unexpected_exception_handling(self):
        """Should handle unexpected exceptions gracefully."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ValueError("Unexpected error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test message", max_retries=1, base_delay=0.01)

        assert result is False

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self):
        """Should use exponential backoff between retries."""
        timeout_exception = httpx.TimeoutException("Timeout")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=timeout_exception)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        sleep_delays = []

        async def capture_sleep(delay):
            sleep_delays.append(delay)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', side_effect=capture_sleep):
                await send_telegram_with_retry("Test", max_retries=3, base_delay=1.0)

        # Delays should be: 1.0, 2.0, 4.0 (exponential)
        assert len(sleep_delays) == 3
        assert sleep_delays[0] == 1.0
        assert sleep_delays[1] == 2.0
        assert sleep_delays[2] == 4.0

    @pytest.mark.asyncio
    async def test_custom_retry_params(self):
        """Should use custom retry parameters when provided."""
        timeout_exception = httpx.TimeoutException("Timeout")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=timeout_exception)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                await send_telegram_with_retry("Test", max_retries=5, base_delay=0.5)

        # Should attempt 6 times (initial + 5 retries)
        assert mock_client.post.call_count == 6

    @pytest.mark.asyncio
    async def test_default_retry_params_from_settings(self):
        """Should use settings defaults when params not provided."""
        timeout_exception = httpx.TimeoutException("Timeout")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=timeout_exception)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                # Use defaults from settings
                await send_telegram_with_retry("Test")

        # Should use settings.telegram_retry_count + 1 attempts
        expected_calls = settings.telegram_retry_count + 1
        assert mock_client.post.call_count == expected_calls

    @pytest.mark.asyncio
    async def test_message_payload_construction(self):
        """Should construct correct payload with chat_id and parse_mode."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            await send_telegram_with_retry("<b>Test</b> message")

        # Verify payload construction
        call_args = mock_client.post.call_args
        url = call_args[0][0]
        payload = call_args[1]['json']

        assert settings.telegram_bot_token in url
        assert payload['chat_id'] == settings.telegram_chat_id
        assert payload['text'] == "<b>Test</b> message"
        assert payload['parse_mode'] == "HTML"


class TestValidateTelegramToken:
    """Tests for validate_telegram_token function."""

    @pytest.mark.asyncio
    async def test_valid_token(self):
        """Should return True for valid token."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true, "result": {"username": "testbot"}}'
        mock_response.json.return_value = {"ok": True, "result": {"username": "testbot"}}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await validate_telegram_token()

        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_token(self):
        """Should return False for invalid token."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = '{"ok": false, "description": "Unauthorized"}'
        mock_response.json.return_value = {"ok": False, "description": "Unauthorized"}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await validate_telegram_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_http_error(self):
        """Should return False on HTTP error."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await validate_telegram_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Should return False on timeout."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await validate_telegram_token()

        assert result is False

    @pytest.mark.asyncio
    async def test_unexpected_exception(self):
        """Should return False on unexpected exception."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ValueError("Unexpected"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await validate_telegram_token()

        assert result is False


class TestSendHealthCheck:
    """Tests for send_health_check function."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Health check should send message and return True on success."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            result = await send_health_check()

        assert result is True
        # Verify message contains health check content
        call_args = mock_client.post.call_args
        payload = call_args[1]['json']
        assert "Health Check" in payload['text']
        assert "Operational" in payload['text']

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Health check should return False on failure."""
        timeout_exception = httpx.TimeoutException("Timeout")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=timeout_exception)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_health_check()

        assert result is False


class TestSendTelegramBackwardCompatibility:
    """Tests for backward compatibility alias."""

    def test_send_telegram_alias_exists(self):
        """send_telegram should be an alias for send_telegram_with_retry."""
        from app.services.notifier import send_telegram
        assert send_telegram is send_telegram_with_retry