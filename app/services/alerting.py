"""
Production-grade alerting and event management module.

Provides structured alert generation, event lifecycle tracking,
and operational messaging for commercial-grade geofencing platform.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Supported event types in the alerting system."""

    ENTRY = "ENTRY"
    ENTERED_GEOFENCE = "ENTERED_GEOFENCE"
    EXIT = "EXIT"
    EXITED_GEOFENCE = "EXITED_GEOFENCE"
    REENTRY = "REENTRY"
    RETURNED_TO_GEOFENCE = "RETURNED_TO_GEOFENCE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    LOW_BATTERY = "LOW_BATTERY"
    GPS_SIGNAL_LOST = "GPS_SIGNAL_LOST"


class SeverityLevel(Enum):
    """Alert severity levels for prioritization."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class AlertContext:
    """
    Structured alert context containing all operational data.

    Attributes:
        event_type: Type of event that triggered the alert
        severity: Severity level for prioritization
        alert_id: Unique identifier for tracking and deduplication
        device_name: Human-readable device identifier
        geofence_name: Name of the geofence (if applicable)
        latitude: Current device latitude
        longitude: Current device longitude
        distance_meters: Distance from geofence center or breach distance
        radius_meters: Geofence radius (if applicable)
        battery_level: Current battery percentage
        timestamp: ISO 8601 timestamp of the event
        previous_state: Previous inside/outside state for transition tracking
        current_state: Current inside/outside state
        google_maps_url: Google Maps link for the position
    """

    event_type: EventType
    severity: SeverityLevel
    alert_id: str
    device_name: str
    geofence_name: Optional[str]
    latitude: float
    longitude: float
    distance_meters: float
    radius_meters: Optional[float]
    battery_level: Optional[int]
    timestamp: datetime
    previous_state: Optional[bool]
    current_state: bool
    google_maps_url: str

    @classmethod
    def create(
        cls,
        event_type: EventType,
        severity: SeverityLevel,
        device_name: str,
        geofence_name: Optional[str],
        latitude: float,
        longitude: float,
        distance_meters: float,
        radius_meters: Optional[float],
        battery_level: Optional[int],
        previous_state: Optional[bool],
        current_state: bool,
    ) -> "AlertContext":
        """Factory method to create alert with generated ID and timestamp."""
        alert_id = str(uuid.uuid4())[:8]
        google_maps_url = f"https://maps.google.com/?q={latitude:.5f},{longitude:.5f}"
        timestamp = datetime.utcnow()

        return cls(
            event_type=event_type,
            severity=severity,
            alert_id=alert_id,
            device_name=device_name,
            geofence_name=geofence_name,
            latitude=latitude,
            longitude=longitude,
            distance_meters=distance_meters,
            radius_meters=radius_meters,
            battery_level=battery_level,
            timestamp=timestamp,
            previous_state=previous_state,
            current_state=current_state,
            google_maps_url=google_maps_url,
        )


def format_telegram_message(ctx: AlertContext) -> str:
    """
    Format alert context into a readable Telegram message.

    Message structure:
    - Event type with emoji
    - Severity level
    - Alert ID for tracking
    - Device and geofence information
    - Position with Google Maps link
    - Distance information
    - Battery level
    - Timestamp

    Returns:
        Formatted message string optimized for mobile reading.
    """
    emoji_map = {
        EventType.EXIT: "🚨",
        EventType.EXITED_GEOFENCE: "🚨",
        EventType.ENTRY: "✅",
        EventType.ENTERED_GEOFENCE: "✅",
        EventType.REENTRY: "🔄",
        EventType.RETURNED_TO_GEOFENCE: "🔄",
        EventType.DEVICE_OFFLINE: "⚠️",
        EventType.LOW_BATTERY: "🔋",
        EventType.GPS_SIGNAL_LOST: "📡",
    }

    emoji = emoji_map.get(ctx.event_type, "ℹ️")

    # Format distance for readability
    if ctx.distance_meters >= 1000:
        distance_str = f"{ctx.distance_meters / 1000:.1f} km"
    else:
        distance_str = f"{ctx.distance_meters:.0f} m"

    # Format battery
    battery_str = f"{ctx.battery_level}%" if ctx.battery_level is not None else "N/A"

    # Format timestamp
    time_str = ctx.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build message with clear sections
    lines = [
        f"{emoji} {ctx.event_type.value.replace('_', ' ')}",
        "",
        f"Severity: {ctx.severity.value}",
        f"Alert ID: {ctx.alert_id}",
        "",
        f"Device: {ctx.device_name}",
    ]

    if ctx.geofence_name:
        lines.append(f"Geofence: {ctx.geofence_name}")

    lines.extend(
        [
            "",
            "Current Position:",
            f"{ctx.latitude:.5f}, {ctx.longitude:.5f}",
            "",
            "Distance Outside:" if ctx.event_type in [EventType.EXIT, EventType.EXITED_GEOFENCE] else "Distance from Center:",
            distance_str,
        ]
    )

    if ctx.radius_meters is not None:
        radius_str = f"{ctx.radius_meters / 1000:.2f} km" if ctx.radius_meters >= 1000 else f"{ctx.radius_meters:.0f} m"
        lines.append(f"Geofence Radius: {radius_str}")

    lines.extend(
        [
            "",
            "Battery:",
            battery_str,
            "",
            "Time:",
            time_str,
            "",
            "Map:",
            ctx.google_maps_url,
        ]
    )

    return "\n".join(lines)


@dataclass
class GeofenceEvaluation:
    """
    Structured logging data for geofence evaluation.

    Provides complete observability for every geofence check operation.

    Attributes:
        evaluation_id: Unique identifier for this evaluation
        geofence_id: Database ID of the geofence
        geofence_name: Human-readable name
        device_id: Device identifier (if available)
        distance_meters: Calculated distance from geofence center
        radius_meters: Geofence radius
        inside: Whether device is currently inside the geofence
        previous_inside: Whether device was previously inside
        decision: Action taken (ALERT_ENTRY, ALERT_EXIT, NONE, COOLDOWN_BLOCKED)
        cooldown_status: Status of cooldown check
        cooldown_minutes: Configured cooldown period
        time_since_last_alert: Minutes since last alert (if any)
    """

    evaluation_id: str
    geofence_id: int
    geofence_name: str
    device_id: Optional[str]
    distance_meters: float
    radius_meters: float
    inside: bool
    previous_inside: Optional[bool]
    decision: str
    cooldown_status: str
    cooldown_minutes: int
    time_since_last_alert: Optional[float]

    def to_log_dict(self) -> dict:
        """Convert to dictionary for structured logging."""
        return {
            "evaluation_id": self.evaluation_id,
            "geofence_id": self.geofence_id,
            "geofence_name": self.geofence_name,
            "device_id": self.device_id,
            "distance_meters": round(self.distance_meters, 2),
            "radius_meters": self.radius_meters,
            "inside": self.inside,
            "previous_inside": self.previous_inside,
            "decision": self.decision,
            "cooldown_status": self.cooldown_status,
            "cooldown_minutes": self.cooldown_minutes,
            "time_since_last_alert_minutes": (
                round(self.time_since_last_alert, 2) if self.time_since_last_alert else None
            ),
        }

    def __str__(self) -> str:
        """Human-readable representation for logs."""
        return (
            f"GeofenceEvaluation("
            f"geofence_id={self.geofence_id}, "
            f"name='{self.geofence_name}', "
            f"distance_m={self.distance_meters:.2f}, "
            f"radius_m={self.radius_meters}, "
            f"inside={self.inside}, "
            f"previous_inside={self.previous_inside}, "
            f"decision={self.decision}, "
            f"cooldown={self.cooldown_status}"
            ")"
        )