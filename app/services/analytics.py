"""
Advanced analytics service for location intelligence.

Implements:
- Speed detection (instant, average, maximum)
- Distance travelled calculation
- Motion trail reconstruction
- GPS anomaly detection (teleport, impossible movement)
- Battery trend analysis and discharge prediction
- Device health scoring
- Tracking quality scoring
- Anomaly counters and reliability metrics
"""

import logging
import math
from datetime import datetime, timedelta

from app.utils.timeutils import now_utc, as_aware
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Location
from app.services.geofence import haversine_meters

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000

SPEED_THRESHOLDS = {
    "walking": 1.5,
    "cycling": 7.0,
    "driving": 30.0,
    "flying": 250.0,
}

ANOMALY_THRESHOLDS = {
    "max_speed_ms": 500.0,
    "max_distance_km": 500.0,
    "min_accuracy_m": 1000.0,
}


def calculate_speed(
    lat1: float, lon1: float, lat2: float, lon2: float, time_delta_seconds: float
) -> Optional[float]:
    """
    Calculate speed between two points in meters per second.

    Args:
        lat1, lon1: First coordinate
        lat2, lon2: Second coordinate
        time_delta_seconds: Time difference in seconds

    Returns:
        Speed in m/s, or None if time delta is zero or negative
    """
    if time_delta_seconds <= 0:
        return None

    distance = haversine_meters(lat1, lon1, lat2, lon2)
    return distance / time_delta_seconds


def get_location_pairs(db: Session, limit: int = 1000) -> list[tuple[Location, Location]]:
    """
    Retrieve consecutive location pairs for analysis.

    Args:
        db: Database session
        limit: Maximum number of pairs to retrieve

    Returns:
        List of (previous, current) location tuples
    """
    locations = (
        db.query(Location)
        .filter(Location.latitude.isnot(None), Location.longitude.isnot(None))
        .order_by(Location.recorded_at.desc())
        .limit(limit + 1)
        .all()
    )

    if len(locations) < 2:
        return []

    pairs = []
    for i in range(len(locations) - 1):
        current = locations[i]
        previous = locations[i + 1]

        if (
            current.latitude is not None
            and current.longitude is not None
            and previous.latitude is not None
            and previous.longitude is not None
        ):
            pairs.append((previous, current))

    return pairs


def calculate_speed_analytics(db: Session, limit: int = 1000) -> dict:
    """
    Calculate speed-related analytics.

    Args:
        db: Database session
        limit: Maximum locations to analyze

    Returns:
        Dictionary with speed metrics
    """
    pairs = get_location_pairs(db, limit)

    if not pairs:
        return {
            "instant_speeds": [],
            "avg_speed_ms": None,
            "max_speed_ms": None,
            "max_speed_kmh": None,
            "speed_samples": 0,
        }

    speeds = []
    for prev, curr in pairs:
        time_delta = (curr.recorded_at - prev.recorded_at).total_seconds()
        speed = calculate_speed(
            prev.latitude, prev.longitude, curr.latitude, curr.longitude, time_delta
        )
        if speed is not None and speed >= 0:
            speeds.append(speed)

    if not speeds:
        return {
            "instant_speeds": [],
            "avg_speed_ms": None,
            "max_speed_ms": None,
            "max_speed_kmh": None,
            "speed_samples": 0,
        }

    avg_speed = sum(speeds) / len(speeds)
    max_speed = max(speeds)

    return {
        "instant_speeds": speeds[-10:],
        "avg_speed_ms": round(avg_speed, 3),
        "max_speed_ms": round(max_speed, 3),
        "max_speed_kmh": round(max_speed * 3.6, 2),
        "speed_samples": len(speeds),
    }


def calculate_distance_analytics(db: Session, hours: int = 24) -> dict:
    """
    Calculate distance travelled analytics.

    Args:
        db: Database session
        hours: Time window in hours

    Returns:
        Dictionary with distance metrics
    """
    cutoff = now_utc() - timedelta(hours=hours)

    locations = (
        db.query(Location)
        .filter(
            Location.recorded_at >= cutoff,
            Location.latitude.isnot(None),
            Location.longitude.isnot(None),
        )
        .order_by(Location.recorded_at)
        .all()
    )

    if len(locations) < 2:
        return {
            "total_distance_m": 0.0,
            "total_distance_km": 0.0,
            "segment_count": 0,
            "avg_segment_distance_m": 0.0,
        }

    total_distance = 0.0
    segments = []

    for i in range(len(locations) - 1):
        dist = haversine_meters(
            locations[i].latitude,
            locations[i].longitude,
            locations[i + 1].latitude,
            locations[i + 1].longitude,
        )
        segments.append(dist)
        total_distance += dist

    avg_segment = total_distance / len(segments) if segments else 0.0

    return {
        "total_distance_m": round(total_distance, 2),
        "total_distance_km": round(total_distance / 1000, 3),
        "segment_count": len(segments),
        "avg_segment_distance_m": round(avg_segment, 2),
    }


def detect_gps_anomalies(db: Session, limit: int = 1000) -> list[dict]:
    """
    Detect GPS anomalies including teleportation and impossible movement.

    Args:
        db: Database session
        limit: Maximum locations to analyze

    Returns:
        List of anomaly records
    """
    pairs = get_location_pairs(db, limit)
    anomalies = []

    for prev, curr in pairs:
        time_delta = (curr.recorded_at - prev.recorded_at).total_seconds()
        if time_delta <= 0:
            continue

        distance = haversine_meters(
            prev.latitude, prev.longitude, curr.latitude, curr.longitude
        )
        speed = distance / time_delta

        anomaly = None

        if speed > ANOMALY_THRESHOLDS["max_speed_ms"]:
            anomaly = {
                "type": "TELEPORT",
                "severity": "CRITICAL",
                "location_id": curr.id,
                "timestamp": curr.recorded_at.isoformat(),
                "distance_m": round(distance, 2),
                "time_delta_s": round(time_delta, 2),
                "speed_ms": round(speed, 2),
                "speed_kmh": round(speed * 3.6, 2),
                "reason": f"Speed {speed:.2f} m/s exceeds threshold {ANOMALY_THRESHOLDS['max_speed_ms']} m/s",
            }
        elif distance > ANOMALY_THRESHOLDS["max_distance_km"] * 1000:
            anomaly = {
                "type": "IMPOSSIBLE_DISTANCE",
                "severity": "HIGH",
                "location_id": curr.id,
                "timestamp": curr.recorded_at.isoformat(),
                "distance_m": round(distance, 2),
                "distance_km": round(distance / 1000, 2),
                "reason": f"Distance {distance/1000:.2f} km exceeds threshold {ANOMALY_THRESHOLDS['max_distance_km']} km",
            }

        if anomaly:
            anomalies.append(anomaly)
            logger.warning(
                f"GPS anomaly detected: {anomaly['type']} at {anomaly['timestamp']}",
                extra=anomaly,
            )

    return anomalies


def calculate_battery_analytics(db: Session, hours: int = 24) -> dict:
    """
    Calculate battery-related analytics including discharge rate prediction.

    Args:
        db: Database session
        hours: Time window in hours

    Returns:
        Dictionary with battery metrics
    """
    cutoff = now_utc() - timedelta(hours=hours)

    locations = (
        db.query(Location)
        .filter(
            Location.recorded_at >= cutoff,
            Location.battery.isnot(None),
        )
        .order_by(Location.recorded_at)
        .all()
    )

    if len(locations) < 2:
        latest = locations[-1] if locations else None
        return {
            "current_battery": latest.battery if latest else None,
            "avg_battery": None,
            "min_battery": None,
            "max_battery": None,
            "discharge_rate_per_hour": None,
            "estimated_hours_remaining": None,
            "battery_samples": len(locations),
        }

    batteries = [loc.battery for loc in locations if loc.battery is not None]

    if not batteries:
        return {
            "current_battery": None,
            "avg_battery": None,
            "min_battery": None,
            "max_battery": None,
            "discharge_rate_per_hour": None,
            "estimated_hours_remaining": None,
            "battery_samples": 0,
        }

    avg_battery = sum(batteries) / len(batteries)
    min_battery = min(batteries)
    max_battery = max(batteries)

    first = locations[0]
    last = locations[-1]

    time_delta_hours = (last.recorded_at - first.recorded_at).total_seconds() / 3600
    battery_delta = first.battery - last.battery

    discharge_rate = battery_delta / time_delta_hours if time_delta_hours > 0 else None

    if discharge_rate and discharge_rate > 0 and last.battery:
        hours_remaining = last.battery / discharge_rate
    else:
        hours_remaining = None

    return {
        "current_battery": last.battery,
        "avg_battery": round(avg_battery, 2),
        "min_battery": min_battery,
        "max_battery": max_battery,
        "discharge_rate_per_hour": round(discharge_rate, 3) if discharge_rate else None,
        "estimated_hours_remaining": round(hours_remaining, 1) if hours_remaining else None,
        "battery_samples": len(batteries),
    }


def calculate_device_health_score(db: Session, hours: int = 24) -> dict:
    """
    Calculate comprehensive device health score (0-100).

    Factors:
    - Uptime (data frequency)
    - GPS quality (anomaly rate)
    - Battery health
    - Data completeness

    Args:
        db: Database session
        hours: Analysis window

    Returns:
        Dictionary with health score and breakdown
    """
    cutoff = now_utc() - timedelta(hours=hours)

    total_locations = (
        db.query(func.count(Location.id))
        .filter(Location.recorded_at >= cutoff)
        .scalar()
    )

    valid_locations = (
        db.query(func.count(Location.id))
        .filter(
            Location.recorded_at >= cutoff,
            Location.latitude.isnot(None),
            Location.longitude.isnot(None),
        )
        .scalar()
    )

    locations_with_battery = (
        db.query(func.count(Location.id))
        .filter(
            Location.recorded_at >= cutoff,
            Location.battery.isnot(None),
        )
        .scalar()
    )

    expected_pings = int(hours * 6)
    uptime_score = min(100, (total_locations / expected_pings * 100)) if expected_pings > 0 else 0

    completeness_score = (valid_locations / total_locations * 100) if total_locations > 0 else 0

    battery_score = (locations_with_battery / total_locations * 100) if total_locations > 0 else 0

    anomalies = detect_gps_anomalies(db, limit=1000)
    anomaly_rate = len(anomalies) / valid_locations if valid_locations > 0 else 0
    gps_quality_score = max(0, 100 - (anomaly_rate * 100))

    health_score = (
        uptime_score * 0.3 + completeness_score * 0.3 + battery_score * 0.2 + gps_quality_score * 0.2
    )

    return {
        "health_score": round(health_score, 2),
        "uptime_score": round(uptime_score, 2),
        "completeness_score": round(completeness_score, 2),
        "battery_score": round(battery_score, 2),
        "gps_quality_score": round(gps_quality_score, 2),
        "anomaly_count": len(anomalies),
        "total_locations": total_locations,
        "valid_locations": valid_locations,
        "analysis_window_hours": hours,
    }


def calculate_tracking_quality_score(db: Session, hours: int = 24) -> dict:
    """
    Calculate tracking quality score based on data freshness and reliability.

    Args:
        db: Database session
        hours: Analysis window

    Returns:
        Dictionary with quality metrics
    """
    latest = db.query(Location).order_by(Location.recorded_at.desc()).first()

    if not latest:
        return {
            "quality_score": 0.0,
            "freshness_score": 0.0,
            "minutes_since_last_update": None,
            "data_status": "NO_DATA",
        }

    minutes_since_update = (now_utc() - as_aware(latest.recorded_at)).total_seconds() / 60

    if minutes_since_update < 5:
        freshness_score = 100.0
        data_status = "EXCELLENT"
    elif minutes_since_update < 15:
        freshness_score = 80.0
        data_status = "GOOD"
    elif minutes_since_update < 30:
        freshness_score = 60.0
        data_status = "FAIR"
    elif minutes_since_update < 60:
        freshness_score = 40.0
        data_status = "POOR"
    else:
        freshness_score = 20.0
        data_status = "STALE"

    quality_score = freshness_score

    if latest.data_quality == "valid":
        quality_score = min(100, quality_score + 10)
    elif latest.data_quality == "degraded":
        quality_score = max(0, quality_score - 10)
    else:
        quality_score = max(0, quality_score - 20)

    return {
        "quality_score": round(quality_score, 2),
        "freshness_score": round(freshness_score, 2),
        "minutes_since_last_update": round(minutes_since_update, 1),
        "last_update": latest.recorded_at.isoformat() if latest else None,
        "data_status": data_status,
        "last_data_quality": latest.data_quality,
    }


def get_comprehensive_analytics(db: Session, hours: int = 24) -> dict:
    """
    Get all analytics in a single call.

    Args:
        db: Database session
        hours: Analysis window

    Returns:
        Comprehensive analytics dictionary
    """
    speed = calculate_speed_analytics(db)
    distance = calculate_distance_analytics(db, hours)
    anomalies = detect_gps_anomalies(db)
    battery = calculate_battery_analytics(db, hours)
    health = calculate_device_health_score(db, hours)
    quality = calculate_tracking_quality_score(db, hours)

    return {
        "speed": speed,
        "distance": distance,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "battery": battery,
        "health": health,
        "quality": quality,
        "generated_at": now_utc().isoformat(),
    }