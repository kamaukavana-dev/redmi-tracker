"""
Analytics router module.

Exposes advanced analytics through API endpoints:
- Speed analytics
- Distance analytics
- GPS anomaly detection
- Battery analytics
- Device health scoring
- Tracking quality metrics
"""

from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_api_key
from app.services import analytics as analytics_svc
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

router = APIRouter(prefix="/analytics", tags=["analytics"])


class SpeedAnalyticsResponse(BaseModel):
    avg_speed_ms: Optional[float]
    max_speed_ms: Optional[float]
    max_speed_kmh: Optional[float]
    speed_samples: int


class DistanceAnalyticsResponse(BaseModel):
    total_distance_m: float
    total_distance_km: float
    segment_count: int
    avg_segment_distance_m: float


class GPSAnomalyResponse(BaseModel):
    type: str
    severity: str
    location_id: int
    timestamp: str
    distance_m: Optional[float]
    speed_ms: Optional[float]
    reason: str


class BatteryAnalyticsResponse(BaseModel):
    current_battery: Optional[int]
    avg_battery: Optional[float]
    min_battery: Optional[int]
    max_battery: Optional[int]
    discharge_rate_per_hour: Optional[float]
    estimated_hours_remaining: Optional[float]
    battery_samples: int


class HealthScoreResponse(BaseModel):
    health_score: float
    uptime_score: float
    completeness_score: float
    battery_score: float
    gps_quality_score: float
    anomaly_count: int
    total_locations: int


class QualityScoreResponse(BaseModel):
    quality_score: float
    freshness_score: float
    minutes_since_last_update: Optional[float]
    data_status: str
    last_data_quality: Optional[str]


class ComprehensiveAnalyticsResponse(BaseModel):
    speed: SpeedAnalyticsResponse
    distance: DistanceAnalyticsResponse
    anomalies: List[GPSAnomalyResponse]
    anomaly_count: int
    battery: BatteryAnalyticsResponse
    health: HealthScoreResponse
    quality: QualityScoreResponse
    generated_at: str


@router.get("/speed", response_model=SpeedAnalyticsResponse)
async def get_speed_analytics(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> SpeedAnalyticsResponse:
    """
    Get speed analytics including average and maximum speed.

    Analyzes consecutive location pairs to calculate instant speeds.
    """
    data = analytics_svc.calculate_speed_analytics(db, limit)
    return SpeedAnalyticsResponse(**data)


@router.get("/distance", response_model=DistanceAnalyticsResponse)
async def get_distance_analytics(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> DistanceAnalyticsResponse:
    """
    Get distance travelled analytics.

    Calculates total distance and average segment distance.
    """
    data = analytics_svc.calculate_distance_analytics(db, hours)
    return DistanceAnalyticsResponse(**data)


@router.get("/anomalies", response_model=List[GPSAnomalyResponse])
async def get_gps_anomalies(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> List[GPSAnomalyResponse]:
    """
    Detect GPS anomalies including teleportation and impossible movement.

    Identifies locations that violate physical constraints.
    """
    anomalies = analytics_svc.detect_gps_anomalies(db, limit)
    return [GPSAnomalyResponse(**a) for a in anomalies]


@router.get("/battery", response_model=BatteryAnalyticsResponse)
async def get_battery_analytics(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> BatteryAnalyticsResponse:
    """
    Get battery analytics including discharge rate prediction.

    Estimates remaining battery life based on discharge trends.
    """
    data = analytics_svc.calculate_battery_analytics(db, hours)
    return BatteryAnalyticsResponse(**data)


@router.get("/health", response_model=HealthScoreResponse)
async def get_device_health(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> HealthScoreResponse:
    """
    Get comprehensive device health score (0-100).

    Factors: uptime, GPS quality, battery health, data completeness.
    """
    data = analytics_svc.calculate_device_health_score(db, hours)
    return HealthScoreResponse(**data)


@router.get("/quality", response_model=QualityScoreResponse)
async def get_tracking_quality(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> QualityScoreResponse:
    """
    Get tracking quality score based on data freshness.

    Indicates how current and reliable the tracking data is.
    """
    data = analytics_svc.calculate_tracking_quality_score(db, hours)
    return QualityScoreResponse(**data)


@router.get("/comprehensive", response_model=ComprehensiveAnalyticsResponse)
async def get_comprehensive_analytics(
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> ComprehensiveAnalyticsResponse:
    """
    Get all analytics in a single call.

    Includes speed, distance, anomalies, battery, health, and quality.
    """
    data = analytics_svc.get_comprehensive_analytics(db, hours)
    return ComprehensiveAnalyticsResponse(**data)