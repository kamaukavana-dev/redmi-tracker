"""
Production-grade alerting system tests.

Tests for:
- Alert context creation and formatting
- Event lifecycle tracking
- Structured logging
- Severity levels and event types
"""

import pytest
from datetime import datetime
from app.services.alerting import (
    AlertContext,
    EventType,
    SeverityLevel,
    GeofenceEvaluation,
    format_telegram_message,
)


class TestEventType:
    """Tests for EventType enum."""

    def test_event_types_defined(self):
        """Verify all required event types are defined."""
        assert EventType.ENTRY.value == "ENTRY"
        assert EventType.ENTERED_GEOFENCE.value == "ENTERED_GEOFENCE"
        assert EventType.EXIT.value == "EXIT"
        assert EventType.EXITED_GEOFENCE.value == "EXITED_GEOFENCE"
        assert EventType.REENTRY.value == "REENTRY"
        assert EventType.RETURNED_TO_GEOFENCE.value == "RETURNED_TO_GEOFENCE"
        assert EventType.DEVICE_OFFLINE.value == "DEVICE_OFFLINE"
        assert EventType.LOW_BATTERY.value == "LOW_BATTERY"
        assert EventType.GPS_SIGNAL_LOST.value == "GPS_SIGNAL_LOST"


class TestSeverityLevel:
    """Tests for SeverityLevel enum."""

    def test_severity_levels_defined(self):
        """Verify all severity levels are defined."""
        assert SeverityLevel.LOW.value == "LOW"
        assert SeverityLevel.MEDIUM.value == "MEDIUM"
        assert SeverityLevel.HIGH.value == "HIGH"
        assert SeverityLevel.CRITICAL.value == "CRITICAL"


class TestAlertContext:
    """Tests for AlertContext dataclass."""

    def test_create_generates_alert_id(self):
        """Verify alert ID is generated and is 8 characters."""
        ctx = AlertContext.create(
            event_type=EventType.EXIT,
            severity=SeverityLevel.HIGH,
            device_name="Test Device",
            geofence_name="Test Fence",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=500,
            radius_meters=100,
            battery_level=85,
            previous_state=True,
            current_state=False,
        )

        assert ctx.alert_id is not None
        assert len(ctx.alert_id) == 8

    def test_create_generates_google_maps_url(self):
        """Verify Google Maps URL is correctly formatted."""
        ctx = AlertContext.create(
            event_type=EventType.EXIT,
            severity=SeverityLevel.HIGH,
            device_name="Test",
            geofence_name="Test",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=500,
            radius_meters=100,
            battery_level=85,
            previous_state=True,
            current_state=False,
        )

        assert "https://maps.google.com/?q=-1.29210,36.82190" in ctx.google_maps_url

    def test_create_sets_timestamp(self):
        """Verify timestamp is set on creation."""
        before = datetime.utcnow()
        ctx = AlertContext.create(
            event_type=EventType.EXIT,
            severity=SeverityLevel.HIGH,
            device_name="Test",
            geofence_name="Test",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=500,
            radius_meters=100,
            battery_level=85,
            previous_state=True,
            current_state=False,
        )
        after = datetime.utcnow()

        assert before <= ctx.timestamp <= after

    def test_create_with_none_battery(self):
        """Verify alert can be created with None battery."""
        ctx = AlertContext.create(
            event_type=EventType.LOW_BATTERY,
            severity=SeverityLevel.MEDIUM,
            device_name="Test",
            geofence_name=None,
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=0,
            radius_meters=None,
            battery_level=None,
            previous_state=None,
            current_state=False,
        )

        assert ctx.battery_level is None
        assert ctx.geofence_name is None


class TestFormatTelegramMessage:
    """Tests for Telegram message formatting."""

    def test_exit_breach_message_format(self):
        """Verify exit breach message contains all required fields."""
        ctx = AlertContext.create(
            event_type=EventType.EXIT,
            severity=SeverityLevel.HIGH,
            device_name="Redmi 14C",
            geofence_name="Home",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=139321,
            radius_meters=10,
            battery_level=57,
            previous_state=True,
            current_state=False,
        )

        message = format_telegram_message(ctx)

        # Check structure
        assert "🚨" in message
        assert "EXIT" in message
        assert "Severity: HIGH" in message
        assert f"Alert ID: {ctx.alert_id}" in message
        assert "Device: Redmi 14C" in message
        assert "Geofence: Home" in message
        assert "-1.29210, 36.82190" in message
        assert "139.3 km" in message  # Formatted as km
        assert "57%" in message
        assert "https://maps.google.com/" in message

    def test_distance_formatting_meters(self):
        """Verify short distances are shown in meters."""
        ctx = AlertContext.create(
            event_type=EventType.EXIT,
            severity=SeverityLevel.HIGH,
            device_name="Test",
            geofence_name="Test",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=500,
            radius_meters=100,
            battery_level=85,
            previous_state=True,
            current_state=False,
        )

        message = format_telegram_message(ctx)
        assert "500 m" in message

    def test_distance_formatting_kilometers(self):
        """Verify long distances are shown in kilometers."""
        ctx = AlertContext.create(
            event_type=EventType.EXIT,
            severity=SeverityLevel.HIGH,
            device_name="Test",
            geofence_name="Test",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=5000,
            radius_meters=100,
            battery_level=85,
            previous_state=True,
            current_state=False,
        )

        message = format_telegram_message(ctx)
        assert "5.0 km" in message

    def test_low_battery_message(self):
        """Verify low battery alert format."""
        ctx = AlertContext.create(
            event_type=EventType.LOW_BATTERY,
            severity=SeverityLevel.MEDIUM,
            device_name="Redmi 14C",
            geofence_name=None,
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=0,
            radius_meters=None,
            battery_level=12,
            previous_state=None,
            current_state=False,
        )

        message = format_telegram_message(ctx)

        assert "🔋" in message
        assert "LOW BATTERY" in message
        assert "12%" in message
        assert "Geofence:" not in message

    def test_device_offline_message(self):
        """Verify device offline alert format."""
        ctx = AlertContext.create(
            event_type=EventType.DEVICE_OFFLINE,
            severity=SeverityLevel.HIGH,
            device_name="Redmi 14C",
            geofence_name=None,
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=0,
            radius_meters=None,
            battery_level=None,
            previous_state=None,
            current_state=False,
        )

        message = format_telegram_message(ctx)

        assert "⚠️" in message
        assert "DEVICE OFFLINE" in message

    def test_gps_signal_lost_message(self):
        """Verify GPS signal lost alert format."""
        ctx = AlertContext.create(
            event_type=EventType.GPS_SIGNAL_LOST,
            severity=SeverityLevel.MEDIUM,
            device_name="Redmi 14C",
            geofence_name=None,
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=0,
            radius_meters=None,
            battery_level=85,
            previous_state=None,
            current_state=False,
        )

        message = format_telegram_message(ctx)

        assert "📡" in message
        assert "GPS SIGNAL LOST" in message

    def test_reentry_message(self):
        """Verify reentry alert format."""
        ctx = AlertContext.create(
            event_type=EventType.REENTRY,
            severity=SeverityLevel.LOW,
            device_name="Redmi 14C",
            geofence_name="Office",
            latitude=-1.2921,
            longitude=36.8219,
            distance_meters=50,
            radius_meters=100,
            battery_level=85,
            previous_state=False,
            current_state=True,
        )

        message = format_telegram_message(ctx)

        assert "🔄" in message
        assert "REENTRY" in message
        assert "Office" in message


class TestGeofenceEvaluation:
    """Tests for GeofenceEvaluation structured logging."""

    def test_evaluation_creation(self):
        """Verify evaluation object is created with all fields."""
        eval = GeofenceEvaluation(
            evaluation_id="abc123",
            geofence_id=5,
            geofence_name="Test Fence",
            device_id="device-001",
            distance_meters=139321,
            radius_meters=10,
            inside=False,
            previous_inside=True,
            decision="EXIT_BREACH",
            cooldown_status="EXPIRED",
            cooldown_minutes=30,
            time_since_last_alert=45.5,
        )

        assert eval.evaluation_id == "abc123"
        assert eval.geofence_id == 5
        assert eval.inside is False
        assert eval.previous_inside is True
        assert eval.decision == "EXIT_BREACH"

    def test_to_log_dict(self):
        """Verify conversion to dictionary for structured logging."""
        eval = GeofenceEvaluation(
            evaluation_id="abc123",
            geofence_id=5,
            geofence_name="Test Fence",
            device_id=None,
            distance_meters=139321.456,
            radius_meters=10,
            inside=False,
            previous_inside=True,
            decision="EXIT_BREACH",
            cooldown_status="EXPIRED",
            cooldown_minutes=30,
            time_since_last_alert=45.5,
        )

        log_dict = eval.to_log_dict()

        assert log_dict["evaluation_id"] == "abc123"
        assert log_dict["geofence_id"] == 5
        assert log_dict["distance_meters"] == 139321.46  # Rounded
        assert log_dict["inside"] is False
        assert log_dict["decision"] == "EXIT_BREACH"

    def test_string_representation(self):
        """Verify human-readable string format."""
        eval = GeofenceEvaluation(
            evaluation_id="abc123",
            geofence_id=5,
            geofence_name="Home",
            device_id=None,
            distance_meters=500,
            radius_meters=100,
            inside=False,
            previous_inside=True,
            decision="EXIT_BREACH",
            cooldown_status="EXPIRED",
            cooldown_minutes=30,
            time_since_last_alert=None,
        )

        str_repr = str(eval)

        assert "geofence_id=5" in str_repr
        assert "name='Home'" in str_repr
        assert "distance_m=500.00" in str_repr
        assert "decision=EXIT_BREACH" in str_repr

    def test_cooldown_blocked_decision(self):
        """Verify cooldown blocked decision is tracked."""
        eval = GeofenceEvaluation(
            evaluation_id="def456",
            geofence_id=3,
            geofence_name="Office",
            device_id=None,
            distance_meters=200,
            radius_meters=100,
            inside=False,
            previous_inside=True,
            decision="EXIT_BREACH_COOLDOWN_BLOCKED",
            cooldown_status="ACTIVE (25.0m remaining)",
            cooldown_minutes=30,
            time_since_last_alert=5.0,
        )

        assert eval.decision == "EXIT_BREACH_COOLDOWN_BLOCKED"
        assert "ACTIVE" in eval.cooldown_status