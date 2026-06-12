"""
Cooldown and race condition tests.

Tests geofence cooldown logic and concurrent access scenarios.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.services.geofence import (
    is_cooldown_active,
    check_all_geofences,
    Geofence,
    Location,
)
from app.config import settings


class TestCooldownLogic:
    """Tests for geofence cooldown functionality."""

    def test_cooldown_active_immediately_after_alert(self):
        """Cooldown should be active immediately after an alert."""
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=datetime.utcnow(),
        )

        result = is_cooldown_active(geofence)

        assert result is True

    def test_cooldown_expired_after_30_minutes(self):
        """Cooldown should expire after 30 minutes."""
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=datetime.utcnow() - timedelta(minutes=31),
        )

        result = is_cooldown_active(geofence)

        assert result is False

    def test_cooldown_boundary_at_30_minutes(self):
        """Cooldown should still be active at exactly 29 minutes 59 seconds."""
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=datetime.utcnow() - timedelta(minutes=29, seconds=59),
        )

        result = is_cooldown_active(geofence)

        assert result is True

    def test_no_cooldown_without_previous_alert(self):
        """No cooldown should be active if never alerted before."""
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=None,
        )

        result = is_cooldown_active(geofence)

        assert result is False


class TestCooldownRaceConditions:
    """Tests for race conditions in cooldown logic."""

    @pytest.fixture
    def real_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        yield db
        db.close()

    def test_concurrent_breaches_same_geofence_single_alert(self, real_db):
        geofence = Geofence(name="Test Fence", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        real_db.add(geofence)
        real_db.commit()
        
        location1 = Location(latitude=-1.3000, longitude=36.8300, battery=85, recorded_at=datetime.utcnow())
        location2 = Location(latitude=-1.3001, longitude=36.8301, battery=84, recorded_at=datetime.utcnow() + timedelta(seconds=10))
        
        with patch.object(settings, 'geofence_cooldown_minutes', 30):
            alerts1 = check_all_geofences(real_db, location1)
            alerts2 = check_all_geofences(real_db, location2)

        assert len(alerts1) == 1
        assert len(alerts2) == 0

    def test_different_geofences_can_alert_simultaneously(self, real_db):
        g1 = Geofence(name="F1", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        g2 = Geofence(name="F2", latitude=-1.3000, longitude=36.8300, radius_meters=500, is_active=True)
        real_db.add_all([g1, g2])
        real_db.commit()

        location = Location(latitude=-1.3100, longitude=36.8400, battery=85, recorded_at=datetime.utcnow())
        with patch.object(settings, 'geofence_cooldown_minutes', 30):
            alerts = check_all_geofences(real_db, location)

        assert len(alerts) == 2

    def test_cooldown_prevents_rapid_successive_alerts(self, real_db):
        g = Geofence(name="Test", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        real_db.add(g)
        real_db.commit()

        location = Location(latitude=-1.3000, longitude=36.8300, battery=85, recorded_at=datetime.utcnow())
        with patch.object(settings, 'geofence_cooldown_minutes', 30):
            alerts = []
            for _ in range(10):
                alerts.extend(check_all_geofences(real_db, location))

        assert len(alerts) == 1
