"""
Comprehensive geofence service tests.

Tests haversine_meters and check_all_geofences functions with SQLite in-memory database.
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Geofence, Location, Alert
from app.services.geofence import (
    haversine_meters,
    check_all_geofences,
    create_geofence,
    delete_geofence,
)
from app.config import settings


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
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def sample_geofence(db_session):
    geofence = Geofence(
        name="Test Fence",
        latitude=-1.2921,
        longitude=36.8219,
        radius_meters=500,
        is_active=True,
    )
    db_session.add(geofence)
    db_session.commit()
    db_session.refresh(geofence)
    yield geofence
    db_session.query(Alert).filter_by(geofence_id=geofence.id).delete()
    db_session.delete(geofence)
    db_session.commit()


@pytest.fixture(scope="function")
def sample_location_inside(db_session):
    location = Location(
        latitude=-1.2921,
        longitude=36.8219,
        battery=85,
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    return location


@pytest.fixture(scope="function")
def sample_location_outside(db_session):
    location = Location(
        latitude=-1.2971,
        longitude=36.8219,
        battery=85,
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    return location


class TestHaversineMeters:
    """Tests for haversine_meters function."""

    def test_same_point_returns_zero(self):
        distance = haversine_meters(-1.2921, 36.8219, -1.2921, 36.8219)
        assert distance == 0.0

    def test_nairobi_to_nakuru_approximate(self):
        nairobi_lat, nairobi_lon = -1.2921, 36.8219
        nakuru_lat, nakuru_lon = -0.3031, 36.0800
        distance = haversine_meters(nairobi_lat, nairobi_lon, nakuru_lat, nakuru_lon)
        assert abs(distance - 157_000) < 30_000

    def test_negative_coordinates_work(self):
        distance = haversine_meters(-33.8688, -151.2093, -33.8688, -151.2093)
        assert distance == 0.0

        distance2 = haversine_meters(-33.8688, -151.2093, -34.0, -151.5)
        assert distance2 > 0


class TestCheckAllGeofences:
    """Tests for check_all_geofences function."""

    def test_phone_inside_geofence_no_breach(self, db_session, sample_geofence):
        location = Location(
            latitude=sample_geofence.latitude,
            longitude=sample_geofence.longitude,
            battery=85,
        )
        db_session.add(location)
        db_session.commit()
        db_session.refresh(location)

        messages = check_all_geofences(db_session, location)
        assert messages == []

    def test_phone_outside_geofence_breach(self, db_session, sample_geofence):
        from app.services.alerting import AlertContext

        location = Location(
            latitude=sample_geofence.latitude + 0.01,
            longitude=sample_geofence.longitude,
            battery=85,
        )
        db_session.add(location)
        db_session.commit()
        db_session.refresh(location)

        alerts = check_all_geofences(db_session, location)
        assert len(alerts) == 1
        assert isinstance(alerts[0], AlertContext)
        assert alerts[0].geofence_name == "Test Fence"
        assert alerts[0].distance_meters > 0

    def test_cooldown_active_blocks_repeat_alert(self, db_session, sample_geofence):
        sample_geofence.last_alerted_at = datetime.utcnow() - timedelta(minutes=5)
        db_session.commit()

        location = Location(
            latitude=sample_geofence.latitude + 0.01,
            longitude=sample_geofence.longitude,
            battery=85,
        )
        db_session.add(location)
        db_session.commit()
        db_session.refresh(location)

        messages = check_all_geofences(db_session, location)
        assert messages == []

    def test_cooldown_expired_allows_alert(self, db_session, sample_geofence):
        from app.services.alerting import AlertContext

        sample_geofence.last_alerted_at = datetime.utcnow() - timedelta(minutes=60)
        db_session.commit()

        location = Location(
            latitude=sample_geofence.latitude + 0.01,
            longitude=sample_geofence.longitude,
            battery=85,
        )
        db_session.add(location)
        db_session.commit()
        db_session.refresh(location)

        alerts = check_all_geofences(db_session, location)
        assert len(alerts) == 1
        assert isinstance(alerts[0], AlertContext)

    def test_no_active_geofences_returns_empty(self, db_session):
        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
        )
        db_session.add(location)
        db_session.commit()
        db_session.refresh(location)

        messages = check_all_geofences(db_session, location)
        assert messages == []

    def test_multiple_geofences_only_breached_return_messages(self, db_session):
        from app.services.alerting import AlertContext

        fence1 = Geofence(
            name="Fence1",
            latitude=-1.2921,
            longitude=36.8219,
            radius_meters=500,
            is_active=True,
        )
        fence2 = Geofence(
            name="Fence2",
            latitude=-0.3031,
            longitude=36.0800,
            radius_meters=150000,
            is_active=True,
        )
        db_session.add(fence1)
        db_session.add(fence2)
        db_session.commit()

        location = Location(
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
        )
        db_session.add(location)
        db_session.commit()
        db_session.refresh(location)

        alerts = check_all_geofences(db_session, location)
        assert len(alerts) == 0

        location2 = Location(
            latitude=-1.2800,
            longitude=36.8219,
            battery=85,
        )
        db_session.add(location2)
        db_session.commit()
        db_session.refresh(location2)

        alerts = check_all_geofences(db_session, location2)
        assert len(alerts) == 1
        assert isinstance(alerts[0], AlertContext)
        assert alerts[0].geofence_name == "Fence1"

        db_session.query(Alert).filter(Alert.geofence_id.in_([fence1.id, fence2.id])).delete(synchronize_session=False)
        for fence in [fence1, fence2]:
            db_session.delete(fence)
        for loc in [location, location2]:
            db_session.delete(loc)
        db_session.commit()


class TestCreateGeofence:
    """Tests for create_geofence function."""

    def test_creates_geofence_with_correct_fields(self, db_session):
        payload = {
            "name": "New Fence",
            "latitude": -1.2921,
            "longitude": 36.8219,
            "radius_meters": 1000,
        }

        result = create_geofence(db_session, payload)

        assert result.name == "New Fence"
        assert result.latitude == -1.2921
        assert result.longitude == 36.8219
        assert result.radius_meters == 1000
        assert result.is_active is True

    def test_returns_geofence_with_assigned_id(self, db_session):
        payload = {
            "name": "ID Test Fence",
            "latitude": -1.2921,
            "longitude": 36.8219,
            "radius_meters": 500,
        }

        result = create_geofence(db_session, payload)

        assert result.id is not None
        assert isinstance(result.id, int)
        assert result.id > 0


class TestDeleteGeofence:
    """Tests for delete_geofence function."""

    def test_sets_is_active_to_false(self, db_session, sample_geofence):
        assert sample_geofence.is_active is True

        result = delete_geofence(db_session, sample_geofence.id)

        assert result is not None
        assert result.is_active is False

    def test_returns_none_for_non_existent_id(self, db_session):
        result = delete_geofence(db_session, 9999)
        assert result is None