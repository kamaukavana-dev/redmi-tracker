"""
Production-grade geofence state machine.

Implements state-driven geofencing with explicit state transitions:
- UNKNOWN: No previous state known
- INSIDE: Device is within geofence boundary
- OUTSIDE: Device is outside geofence boundary
- OFFLINE: Device has not reported recently

State transitions only - no distance-only alerts.
No duplicate alerts.
No scheduler-generated spam.
No undefined state behavior.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Geofence, Alert, Location
from app.services.alerting import AlertContext, EventType, SeverityLevel
from app.services.geofence import haversine_meters, format_telegram_message
from app.utils.timeutils import now_utc, as_aware

logger = logging.getLogger(__name__)


class GeofenceState(Enum):
    """Explicit geofence states for deterministic tracking."""

    UNKNOWN = "UNKNOWN"
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    OFFLINE = "OFFLINE"


class StateTransition(Enum):
    """Valid state transitions with associated events."""

    UNKNOWN_TO_INSIDE = "UNKNOWN_TO_INSIDE"
    UNKNOWN_TO_OUTSIDE = "UNKNOWN_TO_OUTSIDE"
    UNKNOWN_TO_OFFLINE = "UNKNOWN_TO_OFFLINE"
    INSIDE_TO_OUTSIDE = "INSIDE_TO_OUTSIDE"
    INSIDE_TO_OFFLINE = "INSIDE_TO_OFFLINE"
    OUTSIDE_TO_INSIDE = "OUTSIDE_TO_INSIDE"
    OUTSIDE_TO_OFFLINE = "OUTSIDE_TO_OFFLINE"
    OFFLINE_TO_INSIDE = "OFFLINE_TO_INSIDE"
    OFFLINE_TO_OUTSIDE = "OFFLINE_TO_OUTSIDE"
    NO_CHANGE = "NO_CHANGE"


def get_state_transition_event(transition: StateTransition) -> Optional[EventType]:
    """Map state transitions to alert events."""
    mapping = {
        StateTransition.UNKNOWN_TO_OUTSIDE: EventType.EXITED_GEOFENCE,
        StateTransition.INSIDE_TO_OUTSIDE: EventType.EXIT,
        StateTransition.OUTSIDE_TO_INSIDE: EventType.ENTRY,
        StateTransition.OFFLINE_TO_OUTSIDE: EventType.EXITED_GEOFENCE,
        StateTransition.OFFLINE_TO_INSIDE: EventType.ENTRY,
    }
    return mapping.get(transition)


def get_state_transition_severity(transition: StateTransition) -> SeverityLevel:
    """Determine alert severity based on transition type."""
    high_severity = {
        StateTransition.UNKNOWN_TO_OUTSIDE,
        StateTransition.INSIDE_TO_OUTSIDE,
        StateTransition.OFFLINE_TO_OUTSIDE,
    }
    if transition in high_severity:
        return SeverityLevel.HIGH
    return SeverityLevel.MEDIUM


def evaluate_geofence_state(
    geofence: Geofence,
    location: Location,
    previous_state: Optional[GeofenceState],
    last_alert_time: Optional[datetime],
) -> tuple[GeofenceState, StateTransition, bool]:
    """
    Evaluate current geofence state and determine if transition occurred.

    Args:
        geofence: Geofence to evaluate
        location: Current device location
        previous_state: Previous known state (None if unknown)
        last_alert_time: Time of last alert for this geofence

    Returns:
        Tuple of (current_state, transition, should_alert)
    """
    now = now_utc()

    if location.latitude is None or location.longitude is None:
        return GeofenceState.OFFLINE, StateTransition.NO_CHANGE, False

    time_since_update = (now - as_aware(location.recorded_at)).total_seconds() / 60

    if time_since_update > settings.offline_threshold_minutes:
        current_state = GeofenceState.OFFLINE
    else:
        distance = haversine_meters(
            location.latitude,
            location.longitude,
            geofence.latitude,
            geofence.longitude,
        )
        if distance <= geofence.radius_meters:
            current_state = GeofenceState.INSIDE
        else:
            current_state = GeofenceState.OUTSIDE

    if previous_state is None:
        if current_state == GeofenceState.OFFLINE:
            transition = StateTransition.UNKNOWN_TO_OFFLINE
        elif current_state == GeofenceState.INSIDE:
            transition = StateTransition.UNKNOWN_TO_INSIDE
        else:
            transition = StateTransition.UNKNOWN_TO_OUTSIDE
    elif previous_state == current_state:
        transition = StateTransition.NO_CHANGE
    else:
        transition_map = {
            (GeofenceState.INSIDE, GeofenceState.OUTSIDE): StateTransition.INSIDE_TO_OUTSIDE,
            (GeofenceState.OUTSIDE, GeofenceState.INSIDE): StateTransition.OUTSIDE_TO_INSIDE,
            (GeofenceState.INSIDE, GeofenceState.OFFLINE): StateTransition.INSIDE_TO_OFFLINE,
            (GeofenceState.OUTSIDE, GeofenceState.OFFLINE): StateTransition.OUTSIDE_TO_OFFLINE,
            (GeofenceState.OFFLINE, GeofenceState.INSIDE): StateTransition.OFFLINE_TO_INSIDE,
            (GeofenceState.OFFLINE, GeofenceState.OUTSIDE): StateTransition.OFFLINE_TO_OUTSIDE,
        }
        transition = transition_map.get((previous_state, current_state), StateTransition.NO_CHANGE)

    should_alert = False
    if transition != StateTransition.NO_CHANGE:
        event_type = get_state_transition_event(transition)
        if event_type:
            cooldown_active = False
            if last_alert_time:
                cooldown_delta = timedelta(minutes=settings.geofence_cooldown_minutes)
                cooldown_active = (now - as_aware(last_alert_time)) < cooldown_delta

            if not cooldown_active:
                should_alert = True

    return current_state, transition, should_alert


def get_previous_state_from_db(db: Session, geofence_id: int, device_id: str = "default") -> Optional[GeofenceState]:
    """
    Retrieve previous state from database.

    States are stored in a JSON metadata field or inferred from last alert.
    For backward compatibility, infers from alert history if no explicit state.

    Args:
        db: Database session
        geofence_id: Geofence to query
        device_id: Device identifier (for multi-device support)

    Returns:
        Previous GeofenceState or None if unknown
    """
    last_alert = (
        db.query(Alert)
        .filter(Alert.geofence_id == geofence_id)
        .order_by(Alert.sent_at.desc())
        .first()
    )

    if not last_alert:
        return None

    if "EXIT" in last_alert.message or "OUTSIDE" in last_alert.message:
        return GeofenceState.OUTSIDE
    elif "ENTRY" in last_alert.message or "INSIDE" in last_alert.message:
        return GeofenceState.INSIDE

    return None


def check_all_geofences_stateful(db: Session, location: Location, device_id: str = "default") -> list[AlertContext]:
    """
    Check all active geofences using state machine logic.

    Args:
        db: Database session
        location: Current device location
        device_id: Device identifier

    Returns:
        List of AlertContext objects for state transitions
    """
    if location.latitude is None or location.longitude is None:
        logger.warning(
            f"Skipping stateful geofence evaluation for location ID {location.id}: "
            f"Missing coordinates"
        )
        return []

    alerts = []
    active_fences = db.query(Geofence).filter(Geofence.is_active == True).all()

    logger.info(
        f"Stateful geofence evaluation: {len(active_fences)} active geofence(s)",
        extra={
            "location_id": location.id,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "battery": location.battery,
        },
    )

    now = now_utc()
    cooldown_cutoff = now - timedelta(minutes=settings.geofence_cooldown_minutes)

    for fence in active_fences:
        previous_state = get_previous_state_from_db(db, fence.id, device_id)
        current_state, transition, should_alert = evaluate_geofence_state(
            fence, location, previous_state, fence.last_alerted_at
        )

        logger.info(
            f"Geofence '{fence.name}' state evaluation",
            extra={
                "geofence_id": fence.id,
                "geofence_name": fence.name,
                "previous_state": previous_state.value if previous_state else "UNKNOWN",
                "current_state": current_state.value,
                "transition": transition.value,
                "should_alert": should_alert,
            },
        )

        if should_alert:
            event_type = get_state_transition_event(transition)
            severity = get_state_transition_severity(transition)

            distance = haversine_meters(
                location.latitude,
                location.longitude,
                fence.latitude,
                fence.longitude,
            )

            alert_ctx = AlertContext.create(
                event_type=event_type,
                severity=severity,
                device_name=settings.device_name,
                geofence_name=fence.name,
                latitude=location.latitude,
                longitude=location.longitude,
                distance_meters=distance,
                radius_meters=fence.radius_meters,
                battery_level=location.battery,
                previous_state=previous_state.value if previous_state else None,
                current_state=current_state.value,
            )

            message = format_telegram_message(alert_ctx)

            stmt = update(Geofence).where(
                Geofence.id == fence.id,
                or_(
                    Geofence.last_alerted_at.is_(None),
                    Geofence.last_alerted_at <= cooldown_cutoff,
                ),
            ).values(last_alerted_at=now).execution_options(synchronize_session=False)

            result = db.execute(stmt)

            if getattr(result, "rowcount", 1) > 0:
                db_alert = Alert(
                    geofence_id=fence.id,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    message=message,
                )
                db.add(db_alert)
                alerts.append(alert_ctx)

                logger.info(
                    f"State transition alert generated: {alert_ctx.alert_id}",
                    extra={
                        "alert_id": alert_ctx.alert_id,
                        "transition": transition.value,
                        "geofence_name": fence.name,
                    },
                )

    if alerts:
        db.commit()
        logger.info(f"Stateful evaluation generated {len(alerts)} alert(s)")
    else:
        logger.debug("No state transition alerts generated")

    return alerts


def get_state_machine_diagram() -> str:
    """
    Generate ASCII state machine diagram.

    Returns:
        State machine diagram as string
    """
    return """
┌─────────────────────────────────────────────────────────────────────┐
│                    GEOFENCE STATE MACHINE                           │
└─────────────────────────────────────────────────────────────────────┘

                         ┌─────────────┐
                         │   UNKNOWN   │
                         │  (initial)  │
                         └──────┬──────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
              ▼                 ▼                 ▼
    ┌─────────────────┐ ┌─────────────┐ ┌──────────────────┐
    │  UNKNOWN_TO_    │ │ UNKNOWN_TO_ │ │  UNKNOWN_TO_     │
    │    INSIDE       │ │   OUTSIDE   │ │    OFFLINE       │
    └────────┬────────┘ └──────┬──────┘ └────────┬─────────┘
             │                 │                  │
             ▼                 ▼                  ▼
    ┌─────────────┐   ┌─────────────┐    ┌─────────────┐
    │   INSIDE    │   │   OUTSIDE   │    │   OFFLINE   │
    └──────┬──────┘   └──────┬──────┘    └──────┬──────┘
           │                 │                  │
     ┌─────┴─────┐     ┌─────┴─────┐      ┌────┴────┐
     │           │     │           │      │         │
     ▼           │     ▼           │      ▼         ▼
┌─────────┐     │  ┌─────────┐    │  ┌─────────┐ ┌─────────┐
│ INSIDE_ │     │  │OUTSIDE_ │    │  │OFFLINE_ │ │OFFLINE_ │
│ OFFLINE │     │  │ INSIDE  │    │  │ INSIDE  │ │OUTSIDE  │
└────┬────┘     │  └────┬────┘    │  └────┬────┘ └────┬────┘
     │           │       │          │       │          │
     │           │       │          │       │          │
     │           │       │          │       │          │
     └───────────┴───────┴──────────┴───────┴──────────┘
                         │
                         ▼
              ┌──────────────────┐
              │   NO_CHANGE      │
              │ (same state)     │
              └──────────────────┘

STATE TRANSITIONS THAT TRIGGER ALERTS:
  • UNKNOWN → OUTSIDE (initial breach)
  • INSIDE → OUTSIDE (exit breach)
  • OFFLINE → OUTSIDE (return from offline)
  • OUTSIDE → INSIDE (re-entry notification)
  • OFFLINE → INSIDE (return from offline)

STATE TRANSITIONS THAT DO NOT TRIGGER ALERTS:
  • UNKNOWN → INSIDE (initial inside, no alert needed)
  • UNKNOWN → OFFLINE (device never online)
  • INSIDE → OFFLINE (device went offline while inside)
  • OUTSIDE → OFFLINE (device went offline while outside)
  • NO_CHANGE (staying in same state)

COOLDOWN PROTECTION:
  • All alert-triggering transitions respect cooldown period
  • Prevents duplicate/spam alerts during boundary oscillation
"""