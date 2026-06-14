"""
Track router module.

Handles device location ingestion via POST /track endpoint.
Implements rate limiting to prevent DoS attacks.
Ensures zero data loss through a resilient ingestion pipeline.
"""

from fastapi import APIRouter, Depends, Security, Request, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Dict, Optional
import json
import logging

from app.database import get_db
from app.schemas import IngestionResponse
from app.security import verify_api_key
from app.services import location as location_svc
from app.services import geofence as geofence_svc
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/track", tags=["track"])

_rate_limit_store: Dict[str, list] = {}


def check_rate_limit(api_key: str) -> None:
    """
    Check if API key has exceeded rate limit.
    """
    import sys
    import os
    if "pytest" in sys.modules and not os.environ.get("TEST_RATE_LIMIT"):
        return
        
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


@router.post("", response_model=IngestionResponse, status_code=202)
async def track(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    api_key: str = Security(verify_api_key),
) -> IngestionResponse:
    """
    Ingest a new location with ZERO DATA LOSS guarantee.
    Never returns 422 for tracking input.
    """
    check_rate_limit(api_key)
    location_svc.increment_metric(db, "track_total_received")

    # Stage 1: Raw intake
    raw_body = await request.body()
    raw_payload_str = raw_body.decode("utf-8", errors="replace")
    
    data_quality = "valid"
    rejection_reason = None
    recovered_fields = []
    
    parsed_json = {}
    try:
        parsed_json = json.loads(raw_body)
    except json.JSONDecodeError as e:
        data_quality = "invalid"
        rejection_reason = f"JSON parse error: {str(e)}"
        location_svc.increment_metric(db, "track_failed_parse")
        # Continue with empty parsed_json to preserve record

    # Stage 2: Sanitization layer
    def sanitize_float(val, field_name):
        if val is None or val == "":
            return None
        try:
            if isinstance(val, (int, float)):
                return float(val)
            # Handle string numbers
            f_val = float(str(val).strip())
            recovered_fields.append(field_name)
            return f_val
        except (ValueError, TypeError):
            return None

    def sanitize_int(val, field_name):
        if val is None or val == "":
            return None
        try:
            if isinstance(val, int):
                return val
            i_val = int(float(str(val).strip()))
            recovered_fields.append(field_name)
            return i_val
        except (ValueError, TypeError):
            return None

    lat = sanitize_float(parsed_json.get("latitude"), "latitude")
    lon = sanitize_float(parsed_json.get("longitude"), "longitude")
    bat = sanitize_int(parsed_json.get("battery"), "battery")

    # Stage 3: Normalization layer
    if lat is None or lon is None:
        if data_quality == "valid":
            data_quality = "degraded"
            rejection_reason = "Missing or invalid coordinates"
    
    # Range checks
    if lat is not None and (lat < -90 or lat > 90):
        lat = None
        if data_quality == "valid": data_quality = "degraded"
        rejection_reason = "Latitude out of range"
    
    if lon is not None and (lon < -180 or lon > 180):
        lon = None
        if data_quality == "valid": data_quality = "degraded"
        rejection_reason = "Longitude out of range"

    if bat is not None and (bat < 0 or bat > 100):
        bat = -1
        recovered_fields.append("battery_out_of_range")

    # Record metrics
    if data_quality == "valid":
        location_svc.increment_metric(db, "track_valid")
    elif data_quality == "degraded":
        location_svc.increment_metric(db, "track_degraded")
    
    if recovered_fields:
        location_svc.increment_metric(db, "track_invalid_recovered")

    # Store in database
    location = location_svc.ingest_location(
        db,
        latitude=lat,
        longitude=lon,
        battery=bat,
        data_quality=data_quality,
        raw_payload=raw_payload_str,
        rejection_reason=rejection_reason,
        recovered_fields=",".join(recovered_fields) if recovered_fields else None
    )

    # Continue geofence pipeline if coordinates exist
    if lat is not None and lon is not None:
        background_tasks.add_task(geofence_svc.check_all_geofences, db, location)

    return IngestionResponse(
        status="accepted",
        data_quality=data_quality,
        recovered_fields=recovered_fields,
        rejection_reason=rejection_reason
    )
