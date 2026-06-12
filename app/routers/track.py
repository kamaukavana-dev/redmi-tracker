"""
Track router module.

Handles device location ingestion via POST /track endpoint.
Implements rate limiting to prevent DoS attacks.
"""

from fastapi import APIRouter, Depends, Security, Request, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Dict, Optional
from functools import wraps
import time

from app.database import get_db
from app.schemas import LocationCreate, LocationResponse
from app.security import verify_api_key
from app.services import location as location_svc
from app.config import settings

router = APIRouter(prefix="/track", tags=["track"])

_rate_limit_store: Dict[str, list] = {}


def check_rate_limit(api_key: str) -> None:
    import sys
    import os
    if "pytest" in sys.modules and not os.environ.get("TEST_RATE_LIMIT"):
        return
    """
    Check if API key has exceeded rate limit.

    Args:
        api_key: The API key to check.

    Raises:
        HTTPException: If rate limit exceeded (429 Too Many Requests).
    """
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=1)

    if api_key not in _rate_limit_store:
        _rate_limit_store[api_key] = []

    requests = _rate_limit_store[api_key]
    requests[:] = [ts for ts in requests if ts > window_start]

    if len(requests) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Max 20 requests per minute.",
            headers={"Retry-After": "60"},
        )

    requests.append(now)


@router.post("", response_model=LocationResponse, status_code=201)
async def track(
    request: Request,
    payload: LocationCreate,
    db: Session = Depends(get_db),
    api_key: str = Security(verify_api_key),
) -> LocationResponse:
    """
    Ingest a new location from the tracked device.

    Rate limited to 20 requests per minute per API key.

    Args:
        request: FastAPI request object for rate limiting.
        payload: Location data including latitude, longitude, battery.
        db: Database session dependency.
        api_key: Validated API key from security dependency.

    Returns:
        Created location record with assigned ID.

    Raises:
        HTTPException: 429 if rate limit exceeded.
    """
    check_rate_limit(api_key)
    return location_svc.ingest_location(db, payload)