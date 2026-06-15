"""
Test module for scheduler functionality.

Tests geofence checking job and cooldown behavior.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, SessionLocal
from app.models import Location, Geofence
from app.scheduler import (
    check_geofences_job,
    check_device_offline_job,
    start_scheduler,
    stop_scheduler,
    scheduler,
)
from app.services import location as location_svc
from app.services import geofence_state as geofence_state_svc
from app.services import geofence as geofence_svc

TEST_DATABASE_URL = "sqlite:///./test_scheduler.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestSchedulerGeofenceJob:
    """Tests for scheduler geofence checking job."""

    @pytest.mark.asyncio
    async def test_job_skips_when_no_location(self):
        """Job should skip gracefully when no location data exists."""
        with patch.object(location_svc, 'get_latest', return_value=None):
            with patch('app.scheduler.logger') as mock_logger:
                await check_geofences_job()
                
                mock_logger.warning.assert_called()
                assert "No location data available" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_runs_with_location_data(self):
        """Job should run when location data exists."""
        db = TestingSessionLocal()
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow(),
        )
        geofence = Geofence(name="Test", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        db.add(location)
        db.add(geofence)
        db.commit()
        db.close()

        with patch('app.scheduler.send_telegram_with_retry', return_value=True):
            with patch('app.scheduler.logger') as mock_logger:
                await check_geofences_job()

        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_handles_telegram_failure(self):
        """Job should handle Telegram failures gracefully."""
        db = TestingSessionLocal()
        # Create location OUTSIDE the geofence to trigger a breach
        location = Location(
            latitude=-1.2921 + 0.01,  # Outside the 500m radius
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow(),
        )
        geofence = Geofence(name="Test", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        db.add(location)
        db.add(geofence)
        db.commit()
        db.close()

        with patch('app.scheduler.send_telegram_with_retry', return_value=False):
            with patch('app.scheduler.logger') as mock_logger:
                await check_geofences_job()

                # Should log error for failed notification
                assert mock_logger.error.call_count >= 1

    @pytest.mark.asyncio
    async def test_job_handles_exceptions(self):
        """Job should handle exceptions without crashing."""
        with patch.object(location_svc, 'get_latest', side_effect=Exception("Test error")):
            with patch('app.scheduler.logger') as mock_logger:
                await check_geofences_job()

                mock_logger.exception.assert_called()
                assert "Geofence job failed with unexpected error" in str(mock_logger.exception.call_args)

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_with_breach_alerts_success(self):
        """Job should send breach alerts successfully."""
        db = TestingSessionLocal()
        # Create location OUTSIDE the geofence to trigger a breach
        location = Location(
            latitude=-1.2921 + 0.01,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow(),
        )
        geofence = Geofence(name="Test", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        db.add(location)
        db.add(geofence)
        db.commit()
        db.close()

        # Mock geofence_state_svc to return a breach alert
        mock_alert = Mock()
        mock_alert.alert_id = "test-alert-123"
        mock_alert.event_type = Mock()
        mock_alert.event_type.value = "EXIT_BREACH"
        mock_alert.severity = Mock()
        mock_alert.severity.value = "HIGH"
        mock_alert.geofence_name = "Test"
        mock_alert.distance_meters = 150.5

        with patch.object(geofence_state_svc, 'check_all_geofences_stateful', return_value=[mock_alert]):
            with patch.object(geofence_svc, 'format_telegram_message', return_value="Test message"):
                with patch('app.scheduler.send_telegram_with_retry', return_value=True) as mock_send:
                    with patch('app.scheduler.logger') as mock_logger:
                        await check_geofences_job()

        mock_send.assert_called()
        assert mock_logger.info.call_count >= 1

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_with_health_alerts(self):
        """Job should send device health alerts."""
        db = TestingSessionLocal()
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=10,  # Low battery
            recorded_at=datetime.utcnow(),
        )
        db.add(location)
        db.commit()
        db.close()

        mock_health_alert = Mock()
        mock_health_alert.alert_id = "health-alert-456"
        mock_health_alert.event_type = Mock()
        mock_health_alert.event_type.value = "LOW_BATTERY"
        mock_health_alert.severity = Mock()
        mock_health_alert.severity.value = "MEDIUM"

        with patch.object(geofence_state_svc, 'check_all_geofences_stateful', return_value=[]):
            with patch.object(geofence_svc, 'check_device_health', return_value=[mock_health_alert]):
                with patch.object(geofence_svc, 'format_telegram_message', return_value="Health message"):
                    with patch('app.scheduler.send_telegram_with_retry', return_value=True) as mock_send:
                        with patch('app.scheduler.logger') as mock_logger:
                            await check_geofences_job()

        mock_send.assert_called()
        mock_logger.info.assert_any_call("Health alert health-alert-456 sent successfully")

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_with_health_alert_failure(self):
        """Job should handle health alert sending failure."""
        db = TestingSessionLocal()
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=10,
            recorded_at=datetime.utcnow(),
        )
        db.add(location)
        db.commit()
        db.close()

        mock_health_alert = Mock()
        mock_health_alert.alert_id = "health-alert-789"
        mock_health_alert.event_type = Mock()
        mock_health_alert.event_type.value = "LOW_BATTERY"
        mock_health_alert.severity = Mock()
        mock_health_alert.severity.value = "MEDIUM"

        with patch.object(geofence_state_svc, 'check_all_geofences_stateful', return_value=[]):
            with patch.object(geofence_svc, 'check_device_health', return_value=[mock_health_alert]):
                with patch.object(geofence_svc, 'format_telegram_message', return_value="Health message"):
                    with patch('app.scheduler.send_telegram_with_retry', return_value=False):
                        with patch('app.scheduler.logger') as mock_logger:
                            await check_geofences_job()

        mock_logger.error.assert_any_call("Failed to send health alert health-alert-789 after retries")

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_handles_db_session_cleanup_on_error(self):
        """Job should close DB session even on error."""
        mock_db = Mock()
        mock_db.close = Mock()

        with patch('app.scheduler.SessionLocal', return_value=mock_db):
            with patch.object(location_svc, 'get_latest', side_effect=Exception("DB error")):
                with patch('app.scheduler.logger'):
                    await check_geofences_job()

        # Session should be closed in finally block
        mock_db.close.assert_called()


class TestCheckDeviceOfflineJob:
    """Tests for check_device_offline_job function."""

    @pytest.mark.asyncio
    async def test_job_no_location_data(self):
        """Job should handle case when no location data exists."""
        with patch.object(location_svc, 'get_latest', return_value=None):
            with patch('app.scheduler.logger') as mock_logger:
                await check_device_offline_job()

        mock_logger.warning.assert_called()
        assert "No location data ever received" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_device_online(self):
        """Job should recognize device is online."""
        db = TestingSessionLocal()
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow(),  # Just now
        )
        db.add(location)
        db.commit()
        db.close()

        with patch('app.scheduler.logger') as mock_logger:
            await check_device_offline_job()

        mock_logger.info.assert_called()
        assert "Device online" in str(mock_logger.info.call_args)

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_device_offline(self):
        """Job should detect offline device and send alert."""
        db = TestingSessionLocal()
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow() - timedelta(minutes=120),  # 2 hours ago
        )
        db.add(location)
        db.commit()
        db.close()

        with patch('app.scheduler.send_telegram_with_retry', return_value=True) as mock_send:
            with patch('app.scheduler.logger') as mock_logger:
                await check_device_offline_job()

        mock_send.assert_called()
        mock_logger.warning.assert_called()
        assert "Device offline" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    @patch('app.scheduler.SessionLocal', new=TestingSessionLocal)
    async def test_job_offline_alert_failure(self):
        """Job should handle offline alert sending failure."""
        db = TestingSessionLocal()
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow() - timedelta(minutes=120),
        )
        db.add(location)
        db.commit()
        db.close()

        with patch('app.scheduler.send_telegram_with_retry', return_value=False):
            with patch('app.scheduler.logger') as mock_logger:
                await check_device_offline_job()

        mock_logger.error.assert_called()
        assert "Failed to send offline alert" in str(mock_logger.error.call_args)

    @pytest.mark.asyncio
    async def test_job_handles_exceptions(self):
        """Job should handle exceptions without crashing."""
        with patch.object(location_svc, 'get_latest', side_effect=Exception("Test error")):
            with patch('app.scheduler.logger') as mock_logger:
                await check_device_offline_job()

        mock_logger.exception.assert_called()
        assert "Device offline check failed" in str(mock_logger.exception.call_args)


class TestSchedulerStartStop:
    """Tests for scheduler start/stop functions."""

    @pytest.mark.asyncio
    async def test_start_scheduler(self):
        """start_scheduler should add jobs and start scheduler."""
        with patch('app.scheduler.logger') as mock_logger:
            with patch.object(scheduler, 'add_job') as mock_add_job:
                with patch.object(scheduler, 'start') as mock_start:
                    start_scheduler()

        # Verify jobs were added (called twice for two jobs)
        assert mock_add_job.call_count == 2
        mock_start.assert_called_once()
        mock_logger.info.assert_called()
        assert "APScheduler started" in str(mock_logger.info.call_args)

    @pytest.mark.asyncio
    async def test_stop_scheduler(self):
        """stop_scheduler should gracefully shut down."""
        with patch('app.scheduler.logger') as mock_logger:
            with patch.object(scheduler, 'shutdown') as mock_shutdown:
                stop_scheduler()

        mock_shutdown.assert_called_once()
        mock_logger.info.assert_called()
        assert "shut down complete" in str(mock_logger.info.call_args)

    @pytest.mark.asyncio
    async def test_start_scheduler_replaces_existing_jobs(self):
        """start_scheduler should replace existing jobs."""
        with patch('app.scheduler.logger'):
            with patch.object(scheduler, 'add_job') as mock_add_job:
                with patch.object(scheduler, 'start'):
                    start_scheduler()
                    # Call again - should replace
                    start_scheduler()

        # Should have added jobs twice (4 calls total)
        assert mock_add_job.call_count == 4