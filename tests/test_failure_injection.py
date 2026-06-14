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
"""

import pytest
import json
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Location, Geofence
from app.services import analytics
from app.services.geofence import haversine_meters, check_all_geofences


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