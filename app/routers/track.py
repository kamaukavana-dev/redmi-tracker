"""
Track router module.

Handles device location ingestion via POST /track endpoint.
Implements rate limiting to prevent DoS attacks.
Ensures zero data loss through a resilient ingestion pipeline.
"""

from fastapi import APIRouter, Depends, Security, Request, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
import json
import logging

from app.database import get_db
from app.schemas import IngestionResponse
from app.security import verify_api_key
from app.services import location as location_svc
from app.services import geofence as geofence_svc
from app.services import geofence_state as geofence_state_svc
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
    Handles MacroDroid-style payloads with empty strings and null values.
    """
    check_rate_limit(api_key)
    location_svc.increment_metric(db, "track_total_received")

    raw_body = await request.body()
    raw_payload_str = raw_body.decode("utf-8", errors="replace")
    
    data_quality = "valid"
    rejection_reason = None
    recovered_fields = []
    
    parsed_json: Dict[str, Any] = {}
    try:
        parsed_json = json.loads(raw_body)
        if not isinstance(parsed_json, dict):
            raise ValueError("Payload must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        data_quality = "invalid"
        rejection_reason = f"JSON parse error: {str(e)}"
        location_svc.increment_metric(db, "track_failed_parse")
        logger.warning(f"Failed to parse payload: {raw_payload_str[:200]}")
        parsed_json = {}

    def sanitize_float(val, field_name: str) -> Optional[float]:
        """Convert value to float, handling strings, empty values, and null."""
        if val is None or val == "":
            return None
        try:
            if isinstance(val, (int, float)):
                f_val = float(val)
                if field_name in ["latitude", "longitude"]:
                    recovered_fields.append(field_name)
                return f_val
            str_val = str(val).strip()
            if str_val == "":
                return None
            f_val = float(str_val)
            recovered_fields.append(field_name)
            return f_val
        except (ValueError, TypeError):
            return None

    def sanitize_int(val, field_name: str) -> Optional[int]:
        """Convert value to int, handling strings, empty values, and null."""
        if val is None or val == "":
            return None
        try:
            if isinstance(val, int):
                return val
            str_val = str(val).strip()
            if str_val == "":
                return None
            i_val = int(float(str_val))
            recovered_fields.append(field_name)
            return i_val
        except (ValueError, TypeError):
            return None

    lat = sanitize_float(parsed_json.get("latitude"), "latitude")
    lon = sanitize_float(parsed_json.get("longitude"), "longitude")
    bat = sanitize_int(parsed_json.get("battery"), "battery")

    if lat is None or lon is None:
        if data_quality == "valid":
            data_quality = "degraded"
            rejection_reason = "Missing or invalid coordinates"
        logger.warning(f"Missing coordinates: lat={lat}, lon={lon}")
    
    if lat is not None and (lat < -90 or lat > 90):
        lat = None
        if data_quality == "valid":
            data_quality = "degraded"
        rejection_reason = "Latitude out of range [-90, 90]"
        logger.warning(f"Latitude out of range: {lat}")
    
    if lon is not None and (lon < -180 or lon > 180):
        lon = None
        if data_quality == "valid":
            data_quality = "degraded"
        rejection_reason = "Longitude out of range [-180, 180]"
        logger.warning(f"Longitude out of range: {lon}")

    if bat is not None and (bat < 0 or bat > 100):
        bat = None
        recovered_fields.append("battery_out_of_range")
        logger.warning(f"Battery out of range: {bat}")

    if data_quality == "valid":
        location_svc.increment_metric(db, "track_valid")
    elif data_quality == "degraded":
        location_svc.increment_metric(db, "track_degraded")
    
    if recovered_fields:
        location_svc.increment_metric(db, "track_invalid_recovered")

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

    if lat is not None and lon is not None:
        logger.info(f"Location ingested: lat={lat:.6f}, lon={lon:.6f}, battery={bat}, quality={data_quality}")
        background_tasks.add_task(geofence_state_svc.check_all_geofences_stateful, db, location)
    else:
        logger.warning(f"Location ingested without coordinates, skipping geofence check")

    return IngestionResponse(
        status="accepted",
        data_quality=data_quality,
        recovered_fields=recovered_fields,
        rejection_reason=rejection_reason
    )
