from fastapi import APIRouter, Depends, Security
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import StatsResponse, Position
from app.security import verify_api_key
from app.services import location as location_svc
from app.services import geofence as geofence_svc

router = APIRouter(tags=["stats"])

@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db), _: str = Security(verify_api_key)) -> StatsResponse:
    total_pings = location_svc.get_total_count(db)
    latest = location_svc.get_latest(db)
    
    last_seen = latest.recorded_at if latest else None
    last_battery = latest.battery if latest else None
    
    last_known_position = None
    if latest and latest.latitude is not None and latest.longitude is not None:
        last_known_position = Position(latitude=latest.latitude, longitude=latest.longitude)

    avg_battery_24h = location_svc.get_average_battery_24h(db)

    locations_24h = location_svc.get_locations_24h(db)
    expected_pings = 288
    actual_pings = len(locations_24h)
    uptime_score = (actual_pings / expected_pings * 100) if expected_pings > 0 else 0.0
    uptime_score = min(uptime_score, 100.0)

    pings_last_hour = location_svc.get_pings_last_hour(db)

    geofences_active = geofence_svc.get_active_count(db)
    alerts_sent_24h = geofence_svc.get_alerts_24h(db)
    
    metrics = location_svc.get_all_metrics(db)

    return StatsResponse(
        total_pings=total_pings,
        last_seen=last_seen,
        last_known_position=last_known_position,
        last_battery=last_battery,
        avg_battery_24h=avg_battery_24h,
        uptime_score=round(uptime_score, 2),
        uptime_score_24h=round(uptime_score, 2),
        geofences_active=geofences_active,
        alerts_sent_24h=alerts_sent_24h,
        pings_last_hour=pings_last_hour,
        track_total_received=metrics.get("track_total_received", 0),
        track_valid=metrics.get("track_valid", 0),
        track_degraded=metrics.get("track_degraded", 0),
        track_invalid_recovered=metrics.get("track_invalid_recovered", 0),
        track_failed_parse=metrics.get("track_failed_parse", 0),
    )
