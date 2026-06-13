"""
Test module for scheduler functionality.

Tests geofence checking job and cooldown behavior.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, SessionLocal
from app.models import Location, Geofence
from app.scheduler import check_geofences_job
from app.services import location as location_svc

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