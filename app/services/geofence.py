"""
Production-grade geofence service module.

Provides geofence calculations, breach detection, and event lifecycle tracking
with comprehensive observability and structured logging.
"""

import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Geofence, Alert, Location
from app.services.alerting import (
    AlertContext,
    EventType,
    SeverityLevel,
    GeofenceEvaluation,
    format_telegram_message,
)

logger = logging.getLogger(__name__)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth.

    Uses the Haversine formula for accuracy across all distances.

    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees

    Returns:
        Distance in meters between the two points.
    """
    R = 6_371_000  # Earth's radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def create_geofence(db: Session, payload: dict) -> Geofence:
    """
    Create a new geofence with validation.

    Args:
        db: Database session
        payload: Dictionary containing name, latitude, longitude, radius_meters

    Returns:
        Created Geofence object with assigned ID.

    Raises:
        ValueError: If payload is invalid or coordinates out of range.
    """
    # Validate coordinates
    if not -90 <= payload["latitude"] <= 90:
        raise ValueError(f"Latitude {payload['latitude']} out of range [-90, 90]")
    if not -180 <= payload["longitude"] <= 180:
        raise ValueError(f"Longitude {payload['longitude']} out of range [-180, 180]")
    if payload["radius_meters"] <= 0:
        raise ValueError(f"Radius must be positive, got {payload['radius_meters']}")

    geofence = Geofence(**payload)
    db.add(geofence)
    db.commit()
    db.refresh(geofence)

    logger.info(f"Created geofence '{geofence.name}' (ID: {geofence.id})")
    return geofence


def list_geofences(db: Session) -> list[Geofence]:
    """Return all active geofences."""
    return db.query(Geofence).filter(Geofence.is_active == True).all()


def get_geofence(db: Session, geofence_id: int) -> Optional[Geofence]:
    """Get a specific geofence by ID."""
    return db.query(Geofence).filter(Geofence.id == geofence_id).first()


def delete_geofence(db: Session, geofence_id: int) -> Optional[Geofence]:
    """
    Soft-delete a geofence by setting is_active to False.

    Returns:
        Deactivated Geofence or None if not found.
    """
    geofence = db.query(Geofence).filter(Geofence.id == geofence_id).first()
    if geofence:
        geofence.is_active = False
        db.commit()
        logger.info(f"Deactivated geofence '{geofence.name}' (ID: {geofence_id})")
    return geofence


def get_cooldown_status(geofence: Geofence) -> tuple[bool, Optional[float], str]:
    """
    Check cooldown status for a geofence.

    Args:
        geofence: Geofence to check

    Returns:
        Tuple of (is_active, minutes_remaining, status_message)
    """
    if geofence.last_alerted_at is None:
        return False, 0.0, "NO_PREVIOUS_ALERT"

    cooldown_delta = timedelta(minutes=settings.geofence_cooldown_minutes)
    time_since_alert = datetime.utcnow() - geofence.last_alerted_at
    remaining = cooldown_delta - time_since_alert

    if remaining.total_seconds() > 0:
        minutes_remaining = remaining.total_seconds() / 60
        return True, minutes_remaining, f"ACTIVE ({minutes_remaining:.1f}m remaining)"
    else:
        return False, 0.0, "EXPIRED"


def is_cooldown_active(geofence: Geofence) -> bool:
    """
    Check if cooldown is currently active for a geofence.

    Backward compatibility function for existing code.

    Args:
        geofence: Geofence to check

    Returns:
        True if cooldown is active, False otherwise.
    """
    is_active, _, _ = get_cooldown_status(geofence)
    return is_active


def evaluate_geofence(
    db: Session,
    geofence: Geofence,
    location: Location,
    previous_inside: Optional[bool],
) -> GeofenceEvaluation:
    """
    Evaluate a single geofence against a location with full observability.

    Args:
        db: Database session
        geofence: Geofence to evaluate
        location: Current device location
        previous_inside: Whether device was inside on last check (None if first check)

    Returns:
        GeofenceEvaluation with complete decision context.
    """
    evaluation_id = str(uuid.uuid4())[:8]

    distance = haversine_meters(
        location.latitude,
        location.longitude,
        geofence.latitude,
        geofence.longitude,
    )

    inside = distance <= geofence.radius_meters
    cooldown_active, cooldown_remaining, cooldown_status = get_cooldown_status(geofence)

    # Determine decision
    if previous_inside is None:
        # First evaluation - no state transition
        decision = "INITIAL_STATE"
    elif previous_inside and not inside:
        # Transition from inside to outside
        if cooldown_active:
            decision = "EXIT_BREACH_COOLDOWN_BLOCKED"
        else:
            decision = "EXIT_BREACH"
    elif not previous_inside and inside:
        # Transition from outside to inside
        decision = "REENTRY"
    else:
        # No state change
        decision = "NO_CHANGE"

    # Calculate time since last alert
    time_since_last = None
    if geofence.last_alerted_at:
        time_since_last = (datetime.utcnow() - geofence.last_alerted_at).total_seconds() / 60

    evaluation = GeofenceEvaluation(
        evaluation_id=evaluation_id,
        geofence_id=geofence.id,
        geofence_name=geofence.name,
        device_id=None,  # Could be extended to track device ID
        distance_meters=distance,
        radius_meters=geofence.radius_meters,
        inside=inside,
        previous_inside=previous_inside,
        decision=decision,
        cooldown_status=cooldown_status,
        cooldown_minutes=settings.geofence_cooldown_minutes,
        time_since_last_alert=time_since_last,
    )

    logger.info(str(evaluation))
    return evaluation


def check_all_geofences(db: Session, location: Location) -> list[AlertContext]:
    """
    Check all active geofences against a location.

    Implements complete event lifecycle tracking with state transitions:
    - EXIT: Device left a geofence
    - REENTRY: Device returned to a geofence
    - ENTRY: Device entered a geofence (first detection)

    Args:
        db: Database session
        location: Current device location

    Returns:
        List of AlertContext objects for events that should trigger notifications.
    """
    alerts: list[AlertContext] = []
    active_fences = list_geofences(db)
    now = datetime.utcnow()
    cooldown_cutoff = now - timedelta(minutes=settings.geofence_cooldown_minutes)

    for fence in active_fences:
        distance = haversine_meters(
            location.latitude,
            location.longitude,
            fence.latitude,
            fence.longitude,
        )

        inside = distance <= fence.radius_meters
        outside = not inside

        # Determine if we should alert
        should_alert = False
        decision = "EVALUATED"

        if fence.last_alerted_at is None:
            # First time checking this geofence
            if outside:
                # Device is outside - this is an initial breach
                should_alert = True
                decision = "INITIAL_BREACH"
            else:
                # Device is inside - no alert needed
                decision = "INITIAL_INSIDE"
        else:
            # We have a previous alert timestamp
            cooldown_active = fence.last_alerted_at > cooldown_cutoff

            # If last_alerted_at is set, we previously alerted for a breach (device was outside)
            # Now check if device is still outside or has returned inside
            if outside:
                # Still outside - check cooldown
                if cooldown_active:
                    decision = "EXIT_BREACH_COOLDOWN_BLOCKED"
                    should_alert = False
                else:
                    # Cooldown expired - allow another alert
                    decision = "EXIT_BREACH"
                    should_alert = True
            else:
                # Device returned inside - no alert, just track reentry
                decision = "REENTRY"
                should_alert = False

        if should_alert:
            # Update last_alerted_at atomically
            stmt = update(Geofence).where(
                Geofence.id == fence.id,
                or_(
                    Geofence.last_alerted_at.is_(None),
                    Geofence.last_alerted_at <= cooldown_cutoff,
                ),
            ).values(last_alerted_at=now)

            result = db.execute(stmt)

            if getattr(result, "rowcount", 1) > 0:
                # Create structured alert context
                alert_ctx = AlertContext.create(
                    event_type=EventType.EXIT,
                    severity=SeverityLevel.HIGH,
                    device_name=settings.device_name,
                    geofence_name=fence.name,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    distance_meters=distance,
                    radius_meters=fence.radius_meters,
                    battery_level=location.battery,
                    previous_state=False,  # Previously outside (breach)
                    current_state=False,   # Still outside
                )

                # Store alert in database
                message = format_telegram_message(alert_ctx)
                db_alert = Alert(
                    geofence_id=fence.id,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    message=message,
                )
                db.add(db_alert)
                alerts.append(alert_ctx)

                logger.info(f"Alert generated: {alert_ctx.alert_id} for geofence {fence.name}")

        # Log evaluation for observability
        cooldown_status = get_cooldown_status(fence)[2] if fence.last_alerted_at else "NO_PREVIOUS_ALERT"
        evaluation = GeofenceEvaluation(
            evaluation_id=str(uuid.uuid4())[:8],
            geofence_id=fence.id,
            geofence_name=fence.name,
            device_id=None,
            distance_meters=distance,
            radius_meters=fence.radius_meters,
            inside=inside,
            previous_inside=not outside if fence.last_alerted_at else None,
            decision=decision,
            cooldown_status=cooldown_status,
            cooldown_minutes=settings.geofence_cooldown_minutes,
            time_since_last_alert=None,
        )
        logger.info(str(evaluation))

    if alerts:
        db.commit()
        logger.info(f"Generated {len(alerts)} alert(s)")
    else:
        logger.debug("No alerts generated")

    return alerts


def check_device_health(
    db: Session,
    latest_location: Optional[Location],
) -> list[AlertContext]:
    """
    Check device health metrics and generate alerts for anomalies.

    Monitors:
    - Device offline (no updates within threshold)
    - Low battery
    - Stale GPS signal

    Args:
        db: Database session
        latest_location: Most recent location from device

    Returns:
        List of AlertContext objects for health-related alerts.
    """
    alerts: list[AlertContext] = []
    now = datetime.utcnow()

    if latest_location is None:
        # No location data at all - device might be offline
        # This would be handled by the scheduler checking for missing data
        return alerts

    # Check battery level
    if latest_location.battery is not None and latest_location.battery < settings.low_battery_threshold:
        alert_ctx = AlertContext.create(
            event_type=EventType.LOW_BATTERY,
            severity=SeverityLevel.MEDIUM,
            device_name=settings.device_name,
            geofence_name=None,
            latitude=latest_location.latitude,
            longitude=latest_location.longitude,
            distance_meters=0,
            radius_meters=None,
            battery_level=latest_location.battery,
            previous_state=None,
            current_state=False,
        )
        alerts.append(alert_ctx)
        logger.info(f"Low battery alert: {latest_location.battery}%")

    # Check for stale GPS (location recorded long ago)
    time_since_recorded = (now - latest_location.recorded_at).total_seconds() / 60
    if time_since_recorded > settings.gps_stale_threshold_minutes:
        alert_ctx = AlertContext.create(
            event_type=EventType.GPS_SIGNAL_LOST,
            severity=SeverityLevel.MEDIUM,
            device_name=settings.device_name,
            geofence_name=None,
            latitude=latest_location.latitude,
            longitude=latest_location.longitude,
            distance_meters=0,
            radius_meters=None,
            battery_level=latest_location.battery,
            previous_state=None,
            current_state=False,
        )
        alerts.append(alert_ctx)
        logger.info(f"GPS stale alert: {time_since_recorded:.0f} minutes old")

    return alerts


def get_active_count(db: Session) -> int:
    """Return count of active geofences."""
    return db.query(func.count(Geofence.id)).filter(Geofence.is_active == True).scalar()


def get_alerts_24h(db: Session) -> int:
    """Return count of alerts generated in last 24 hours."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    return db.query(func.count(Alert.id)).filter(Alert.sent_at >= cutoff).scalar()