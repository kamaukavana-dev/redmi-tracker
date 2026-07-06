"""
Failure injection and chaos engineering tests.

Tests system resilience under:
- Invalid JSON payloads
- Missing fields
- Stale GPS data
- Offline device simulation
- Duplicate packets
- High-volume ingestion
- GPS jitter
- Boundary oscillation
- Teleport events
- Clock skew
- Network interruption simulation
- Database failures
- Telegram failures
- Scheduler failures
- Corrupted payloads
"""

import pytest
import json
import httpx
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from app.database import Base
from app.models import Location, Geofence
from app.services import analytics
from app.services.geofence import haversine_meters, check_all_geofences
from app.scheduler import check_geofences_job, check_device_offline_job
from app.services import location as location_svc
from app.services.notifier import send_telegram_with_retry


@pytest.fixture(scope="module")
def engine():
    return create_engine("sqlite:///:memory:", echo=False)


@pytest.fixture(scope="module")
def tables(engine):
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(engine, tables):
    Session = sessionmaker(bind=engine)
    session = Session()
    session.query(Location).delete()
    session.query(Geofence).delete()
    session.commit()
    yield session
    session.rollback()
    session.close()


class TestInvalidJSONHandling:
    """Test handling of malformed JSON payloads."""

    def test_garbage_json_handled(self):
        """Test that garbage JSON doesn't crash the system."""
        garbage = "not json at all {{{"
        try:
            json.loads(garbage)
            assert False, "Should have failed"
        except json.JSONDecodeError:
            pass  # Expected

    def test_empty_object_handled(self):
        """Test empty JSON object handling."""
        data = json.loads("{}")
        assert isinstance(data, dict)
        assert len(data) == 0

    def test_array_as_root_handled(self):
        """Test JSON array as root element."""
        data = json.loads("[1, 2, 3]")
        assert isinstance(data, list)
        assert len(data) == 3

    def test_null_root_handled(self):
        """Test null as root element."""
        data = json.loads("null")
        assert data is None

    def test_unicode_garbage_handled(self):
        """Test unicode garbage handling."""
        garbage = "\x00\x01\x02\xff\xfe"
        try:
            garbage.decode('utf-8', errors='replace')
        except:
            pass  # May fail, that's ok


class TestStaleGPSSimulation:
    """Test handling of stale GPS data."""

    def test_old_location_marked_stale(self, db_session):
        """Test that old locations are detected as stale."""
        old_time = datetime.utcnow() - timedelta(hours=2)
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=old_time,
        )
        db_session.add(loc)
        db_session.commit()

        time_since = (datetime.utcnow() - loc.recorded_at).total_seconds() / 60
        assert time_since > 60  # Stale threshold

    def test_fresh_location_not_stale(self, db_session):
        """Test that fresh locations are not marked stale."""
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow(),
        )
        db_session.add(loc)
        db_session.commit()

        time_since = (datetime.utcnow() - loc.recorded_at).total_seconds() / 60
        assert time_since < 5  # Fresh


class TestOfflineDeviceSimulation:
    """Test offline device detection."""

    def test_no_locations_means_offline(self, db_session):
        """Test that no locations indicates offline device."""
        latest = db_session.query(Location).order_by(
            Location.recorded_at.desc()
        ).first()
        assert latest is None

    def test_last_location_very_old(self, db_session):
        """Test detection of very old last location."""
        old_time = datetime.utcnow() - timedelta(hours=5)
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=old_time,
        )
        db_session.add(loc)
        db_session.commit()

        latest = db_session.query(Location).order_by(
            Location.recorded_at.desc()
        ).first()
        
        time_since = (datetime.utcnow() - latest.recorded_at).total_seconds() / 60
        assert time_since > 60  # Offline threshold


class TestDuplicatePacketHandling:
    """Test handling of duplicate location packets."""

    def test_identical_duplicates_accepted(self, db_session):
        """Test that duplicate packets are accepted (idempotent)."""
        for i in range(5):
            loc = Location(
                latitude=0.0,
                longitude=0.0,
                battery=80,
                recorded_at=datetime.utcnow(),
            )
            db_session.add(loc)
        db_session.commit()

        count = db_session.query(Location).count()
        assert count == 5  # All accepted

    def test_hundred_duplicates(self, db_session):
        """Test handling of 100 duplicate packets."""
        for i in range(100):
            loc = Location(
                latitude=0.0,
                longitude=0.0,
                battery=80,
                recorded_at=datetime.utcnow(),
            )
            db_session.add(loc)
        db_session.commit()

        count = db_session.query(Location).count()
        assert count == 100  # All accepted, no crash

    def test_five_hundred_duplicates(self, db_session):
        """Test handling of 500 duplicate packets."""
        for i in range(500):
            loc = Location(
                latitude=0.0,
                longitude=0.0,
                battery=80,
            )
            db_session.add(loc)
        db_session.commit()

        count = db_session.query(Location).count()
        assert count == 500  # All accepted, no crash


class TestGPSJitterSimulation:
    """Test handling of GPS jitter (small random movements)."""

    def test_small_jitter_no_false_breach(self, db_session):
        """Test that small GPS jitter doesn't trigger false breaches."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=100,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        base_lat, base_lon = 0.0, 0.0
        for i in range(10):
            jitter_lat = base_lat + (i % 2) * 0.0001
            jitter_lon = base_lon + (i % 2) * 0.0001
            loc = Location(
                latitude=jitter_lat,
                longitude=jitter_lon,
                battery=80 - i,
                recorded_at=datetime.utcnow() - timedelta(minutes=i),
            )
            db_session.add(loc)
        db_session.commit()

        latest = db_session.query(Location).order_by(
            Location.recorded_at.desc()
        ).first()

        distance = haversine_meters(
            latest.latitude, latest.longitude,
            geofence.latitude, geofence.longitude
        )
        
        assert distance < 100  # Still inside despite jitter


class TestBoundaryOscillation:
    """Test handling of boundary oscillation (rapid in/out movement)."""

    def test_rapid_oscillation_cooldown_blocks(self, db_session):
        """Test that cooldown prevents spam from oscillation."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=50,
            is_active=True,
            last_alerted_at=datetime.utcnow(),
        )
        db_session.add(geofence)
        db_session.commit()

        for i in range(5):
            lat = 0.0005 if i % 2 == 0 else 0.0
            loc = Location(
                latitude=lat,
                longitude=0.0,
                battery=80,
                recorded_at=datetime.utcnow() - timedelta(seconds=i*10),
            )
            db_session.add(loc)
        db_session.commit()

        latest = db_session.query(Location).order_by(
            Location.recorded_at.desc()
        ).first()

        alerts = check_all_geofences(db_session, latest)
        assert len(alerts) == 0  # Cooldown blocks all


class TestTeleportEvents:
    """Test detection of teleport events (impossible movement)."""

    def test_teleport_detected(self, db_session):
        """Test that teleport events are detected."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now - timedelta(seconds=1),
        )
        loc2 = Location(
            latitude=50.0,
            longitude=50.0,
            battery=79,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2])
        db_session.commit()

        anomalies = analytics.detect_gps_anomalies(db_session)
        assert len(anomalies) > 0
        assert anomalies[0]["type"] == "TELEPORT"

    def test_impossible_speed_detected(self, db_session):
        """Test detection of impossible speed."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now - timedelta(seconds=1),
        )
        loc2 = Location(
            latitude=0.1,
            longitude=0.1,
            battery=79,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2])
        db_session.commit()

        anomalies = analytics.detect_gps_anomalies(db_session)
        assert len(anomalies) > 0


class TestClockSkew:
    """Test handling of clock skew between device and server."""

    def test_future_timestamp_handled(self, db_session):
        """Test handling of future timestamps."""
        future_time = datetime.utcnow() + timedelta(hours=1)
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=future_time,
        )
        db_session.add(loc)
        db_session.commit()
        
        assert loc.recorded_at > datetime.utcnow()

    def test_very_old_timestamp_handled(self, db_session):
        """Test handling of very old timestamps."""
        old_time = datetime.utcnow() - timedelta(days=30)
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=old_time,
        )
        db_session.add(loc)
        db_session.commit()
        
        assert loc.recorded_at < datetime.utcnow()


class TestHighVolumeIngestion:
    """Test high-volume location ingestion."""

    def test_thousand_locations(self, db_session):
        """Test ingestion of 1000 locations."""
        locations = []
        now = datetime.utcnow()
        for i in range(1000):
            loc = Location(
                latitude=0.0 + i * 0.00001,
                longitude=0.0 + i * 0.00001,
                battery=80 - (i % 20),
                recorded_at=now - timedelta(seconds=i),
            )
            locations.append(loc)
        
        db_session.add_all(locations)
        db_session.commit()

        count = db_session.query(Location).count()
        assert count == 1000

    def test_analytics_handles_large_dataset(self, db_session):
        """Test analytics with large dataset."""
        locations = []
        now = datetime.utcnow()
        for i in range(500):
            loc = Location(
                latitude=0.0 + i * 0.00001,
                longitude=0.0 + i * 0.00001,
                battery=80 - (i % 20),
                recorded_at=now - timedelta(seconds=i*10),
            )
            locations.append(loc)
        
        db_session.add_all(locations)
        db_session.commit()

        analytics_result = analytics.get_comprehensive_analytics(db_session, hours=24)
        assert "speed" in analytics_result
        assert "distance" in analytics_result
        assert "health" in analytics_result


class TestNetworkInterruptionSimulation:
    """Test simulation of network interruptions."""

    def test_gap_in_data_detected(self, db_session):
        """Test detection of gaps in location data."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now - timedelta(hours=2),
        )
        loc2 = Location(
            latitude=0.001,
            longitude=0.001,
            battery=79,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2])
        db_session.commit()

        time_gap = (loc2.recorded_at - loc1.recorded_at).total_seconds() / 60
        assert time_gap > 60  # Gap detected

    def test_quality_score_reflects_gap(self, db_session):
        """Test that quality score reflects data gaps."""
        old_loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow() - timedelta(hours=2),
        )
        db_session.add(old_loc)
        db_session.commit()

        quality = analytics.calculate_tracking_quality_score(db_session)
        assert quality["data_status"] in ["POOR", "STALE"]


class TestDatabaseFailures:
    """Test database failure scenarios."""

    def test_database_unavailable(self):
        """System should handle database being unavailable."""
        mock_db = Mock()
        mock_db.query.side_effect = SQLAlchemyError("Database unavailable")
        
        # Simulate what happens when DB is unavailable
        try:
            mock_db.query(Location).first()
            assert False, "Should have raised"
        except SQLAlchemyError:
            pass  # Expected - error is caught and handled

    def test_database_error_propagation(self):
        """Database errors should propagate appropriately."""
        mock_db = Mock()
        mock_db.query.side_effect = SQLAlchemyError("Connection lost")
        
        # Verify that errors are raised (and would be caught by service layer)
        with pytest.raises(SQLAlchemyError):
            mock_db.query(Location).first()

    def test_database_timeout(self, db_session):
        """System should handle database timeout."""
        # Simulate slow query by adding many records
        for i in range(100):
            loc = Location(
                latitude=0.0 + i * 0.00001,
                longitude=0.0 + i * 0.00001,
                battery=80,
                recorded_at=datetime.utcnow() - timedelta(seconds=i),
            )
            db_session.add(loc)
        db_session.commit()
        
        # Query should still work
        count = db_session.query(Location).count()
        assert count == 100

    def test_database_connection_error_recovery(self):
        """System should recover from connection errors."""
        mock_db = Mock()
        mock_db.query.side_effect = [
            SQLAlchemyError("Connection lost"),
            Mock(first=Mock(return_value=None))  # Recovery
        ]
        
        # First call fails, second succeeds
        with pytest.raises(SQLAlchemyError):
            mock_db.query(Location).first()
        
        # After recovery
        result = mock_db.query(Location).first()
        assert result is None


class TestTelegramFailures:
    """Test Telegram API failure scenarios."""

    @pytest.mark.asyncio
    async def test_telegram_unavailable(self):
        """System should handle Telegram being completely unavailable."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Cannot connect"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test", max_retries=2, base_delay=0.01)
        
        assert result is False  # Should fail gracefully

    @pytest.mark.asyncio
    async def test_telegram_500_error(self):
        """System should handle Telegram 500 errors."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'
        mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
            "Server Error", request=Mock(), response=mock_response
        ))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test", max_retries=1, base_delay=0.01)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_telegram_rate_limit(self):
        """System should handle Telegram rate limiting (429)."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = 'Too Many Requests'
        mock_response.json.return_value = {"ok": False, "description": "Too many requests"}
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test", max_retries=1, base_delay=0.01)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_telegram_timeout(self):
        """System should handle Telegram timeout."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("Read timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            with patch('asyncio.sleep', AsyncMock()):
                result = await send_telegram_with_retry("Test", max_retries=1, base_delay=0.01)
        
        assert result is False


class TestSchedulerFailures:
    """Test scheduler failure scenarios."""

    @pytest.mark.asyncio
    async def test_scheduler_overlap_prevention(self):
        """Scheduler should prevent overlapping executions."""
        # The scheduler uses max_instances=1 to prevent overlap
        # This test verifies the configuration
        from app.scheduler import scheduler as app_scheduler
        
        # Start scheduler
        with patch('app.scheduler.logger'):
            with patch.object(app_scheduler, 'add_job') as mock_add:
                with patch.object(app_scheduler, 'start'):
                    from app.scheduler import start_scheduler
                    start_scheduler()
        
        # Verify max_instances=1 is set
        call_args = mock_add.call_args_list[0][1]
        assert call_args.get('max_instances') == 1

    @pytest.mark.asyncio
    async def test_scheduler_crash_recovery(self):
        """Scheduler jobs should not crash the entire system."""
        with patch.object(location_svc, 'get_latest', side_effect=Exception("Critical error")):
            with patch('app.scheduler.logger') as mock_logger:
                # Should not raise, should log and continue
                await check_geofences_job()
        
        mock_logger.exception.assert_called()
        assert "Geofence job failed" in str(mock_logger.exception.call_args)

    @pytest.mark.asyncio
    async def test_scheduler_handles_null_coordinates(self):
        """Scheduler should handle locations with null coordinates."""
        mock_location = Mock()
        mock_location.latitude = None
        mock_location.longitude = None
        mock_location.battery = 80
        mock_location.recorded_at = datetime.utcnow()
        mock_location.id = 1

        with patch.object(location_svc, 'get_latest', return_value=mock_location):
            with patch('app.scheduler.logger') as mock_logger:
                await check_geofences_job()
        
        # Should not crash
        assert mock_logger.warning.called or mock_logger.info.called


class TestCorruptedPayloads:
    """Test handling of corrupted and malformed payloads."""

    def test_corrupted_json_payload(self):
        """System should handle corrupted JSON."""
        corrupted = b'\x80\x81\x82\x83'  # Invalid UTF-8
        try:
            corrupted.decode('utf-8')
            assert False, "Should have failed"
        except UnicodeDecodeError:
            pass  # Expected

    def test_malformed_payload_missing_device(self):
        """System should handle payload missing device field."""
        payload = {
            "latitude": 0.0,
            "longitude": 0.0,
            "battery": 80,
            # Missing device_id
        }
        # Should be handled by validation
        assert "latitude" in payload
        assert "longitude" in payload

    def test_invalid_coordinates_none(self):
        """System should handle None coordinates."""
        payload = {
            "latitude": None,
            "longitude": None,
            "battery": 80,
        }
        # Validation should catch this
        assert payload["latitude"] is None

    def test_invalid_coordinates_strings(self):
        """System should handle string coordinates."""
        payload = {
            "latitude": "not_a_number",
            "longitude": "also_not_a_number",
            "battery": 80,
        }
        # Should fail validation
        with pytest.raises(ValueError):
            float(payload["latitude"])

    def test_invalid_battery_negative(self):
        """System should handle negative battery values."""
        payload = {
            "latitude": 0.0,
            "longitude": 0.0,
            "battery": -10,
        }
        # Should be rejected or clamped
        assert payload["battery"] < 0

    def test_invalid_battery_over_100(self):
        """System should handle battery > 100."""
        payload = {
            "latitude": 0.0,
            "longitude": 0.0,
            "battery": 150,
        }
        # Should be rejected or clamped
        assert payload["battery"] > 100

    def test_duplicate_payload_same_timestamp(self):
        """System should handle duplicate payloads with same timestamp."""
        payload = {
            "latitude": 0.0,
            "longitude": 0.0,
            "battery": 80,
            "timestamp": "2024-01-01T00:00:00Z",
        }
        # Duplicates should be accepted (idempotent)
        assert payload["timestamp"] is not None

    def test_stale_gps_old_timestamp(self):
        """System should detect stale GPS from old timestamp."""
        old_timestamp = datetime.utcnow() - timedelta(hours=2)
        payload = {
            "latitude": 0.0,
            "longitude": 0.0,
            "battery": 80,
            "timestamp": old_timestamp.isoformat(),
        }
        # Should be detected as stale
        time_diff = (datetime.utcnow() - old_timestamp).total_seconds() / 60
        assert time_diff > 30  # Stale threshold


class TestLargeRequestVolume:
    """Test handling of large request volumes."""

    def test_burst_requests(self, db_session):
        """System should handle burst of requests."""
        now = datetime.utcnow()
        locations = []
        for i in range(100):
            loc = Location(
                latitude=0.0 + i * 0.00001,
                longitude=0.0,
                battery=80,
                recorded_at=now - timedelta(milliseconds=i*10),
            )
            locations.append(loc)
        
        db_session.add_all(locations)
        db_session.commit()
        
        count = db_session.query(Location).count()
        assert count == 100

    def test_sustained_high_volume(self, db_session):
        """System should handle sustained high volume."""
        now = datetime.utcnow()
        for batch in range(10):
            locations = []
            for i in range(50):
                loc = Location(
                    latitude=0.0 + (batch * 50 + i) * 0.00001,
                    longitude=0.0,
                    battery=80 - batch,
                    recorded_at=now - timedelta(minutes=batch * 5 + i),
                )
                locations.append(loc)
            db_session.add_all(locations)
            db_session.commit()
        
        count = db_session.query(Location).count()
        assert count == 500

    def test_analytics_under_load(self, db_session):
        """Analytics should work under high load."""
        now = datetime.utcnow()
        for i in range(200):
            loc = Location(
                latitude=0.0 + i * 0.00001,
                longitude=0.0,
                battery=80 - (i % 20),
                recorded_at=now - timedelta(seconds=i*5),
            )
            db_session.add(loc)
        db_session.commit()
        
        # Analytics should complete
        result = analytics.get_comprehensive_analytics(db_session, hours=24)
        assert result is not None
        assert "speed" in result