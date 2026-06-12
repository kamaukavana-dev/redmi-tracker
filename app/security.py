"""
Security and authentication module.

Provides API key verification using constant-time comparison
to prevent timing attacks.
"""

import secrets
from typing import Optional

from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    Verify API key using constant-time comparison.

    Args:
        api_key: API key from request header.

    Returns:
        The validated API key string.

    Raises:
        HTTPException: If API key is missing or invalid (403 Forbidden).
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing API key. Provide X-API-Key header.",
        )

    if not secrets.compare_digest(api_key.encode(), settings.api_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )

    return api_key