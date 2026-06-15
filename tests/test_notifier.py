import pytest
from unittest.mock import AsyncMock, patch
from app.services.notifier import send_telegram_with_retry, validate_telegram_token
import httpx

from unittest.mock import AsyncMock, patch, MagicMock
@pytest.mark.asyncio
async def test_send_telegram_success():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        # json is a synchronous method, should be a normal Mock
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response
        
        result = await send_telegram_with_retry("test message")
        assert result is True
        assert mock_post.called

@pytest.mark.asyncio
async def test_send_telegram_failure_retry():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Error"
        mock_post.return_value = mock_response
        
        # Patch sleep to make test fast
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await send_telegram_with_retry("test message", max_retries=1)
            assert result is False
            assert mock_post.call_count == 2 # Initial + 1 retry

@pytest.mark.asyncio
async def test_validate_token_success():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"username": "testbot"}}
        mock_get.return_value = mock_response
        
        result = await validate_telegram_token()
        assert result is True

@pytest.mark.asyncio
async def test_validate_token_failure():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        mock_get.side_effect = httpx.HTTPStatusError("Unauthorized", request=None, response=mock_response)
        
        result = await validate_telegram_token()
        assert result is False

@pytest.mark.asyncio
async def test_send_telegram_unexpected_exception():
    with patch("httpx.AsyncClient.post", side_effect=Exception("Unexpected")):
        result = await send_telegram_with_retry("test message")
        assert result is False

@pytest.mark.asyncio
async def test_validate_token_unexpected_exception():
    with patch("httpx.AsyncClient.get", side_effect=Exception("Unexpected")):
        result = await validate_telegram_token()
        assert result is False

from app.services.notifier import send_health_check
@pytest.mark.asyncio
async def test_send_health_check_success():
    with patch("app.services.notifier.send_telegram_with_retry", new_callable=AsyncMock) as mock_retry:
        mock_retry.return_value = True
        result = await send_health_check()
        assert result is True
