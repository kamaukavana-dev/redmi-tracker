"""
Service layer unit tests.

Tests location, geofence, and notifier services with mocked database.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy.orm import Session

from app.services import location as location_svc
from app.services import geofence as geofence_svc
from app.models import Location, Geofence, Alert
from app.schemas import LocationCreate


class TestLocationService:
    """Tests for location service functions."""

    @pytest.fixture
    def mock_db(self):
        db = Mock(spec=Session)
        return db

    def test_ingest_location_success(self, mock_db):
        payload = LocationCreate(latitude=-1.2921, longitude=36.8219, battery=85)
        mock_location = Location(
            id=1,
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        mock_db.add = Mock()
        mock_db.commit = Mock()
        mock_db.refresh = Mock()

        with patch.object(location_svc.Location, '__init__', return_value=None):
            with patch.object(location_svc, 'Location', return_value=mock_location):
                result = location_svc.ingest_location(mock_db, payload)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()
        mock_db.refresh.assert_called()

    def test_get_latest_success(self, mock_db):
        mock_location = Location(
            id=1,
            latitude=-1.2921,
            longitude=36.8219,
            battery=85,
            recorded_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        mock_query = Mock()
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.first = Mock(return_value=mock_location)
        mock_db.query = Mock(return_value=mock_query)

        result = location_svc.get_latest(mock_db)

        assert result == mock_location
        mock_db.query.assert_called_once()

    def test_get_latest_no_data(self, mock_db):
        mock_query = Mock()
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.first = Mock(return_value=None)
        mock_db.query = Mock(return_value=mock_query)

        result = location_svc.get_latest(mock_db)

        assert result is None

    def test_get_history_with_cursor(self, mock_db):
        mock_query = Mock()
        mock_query.order_by = Mock(return_value=mock_query)
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.limit = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[
            Location(id=5, latitude=-1.29, longitude=36.82, battery=80, recorded_at=datetime.utcnow()),
            Location(id=4, latitude=-1.28, longitude=36.81, battery=79, recorded_at=datetime.utcnow()),
        ])

        mock_count_query = Mock()
        mock_count_query.scalar = Mock(return_value=100)

        mock_db.query = Mock(side_effect=[mock_count_query, mock_query])

        locations, next_cursor, total = location_svc.get_history(mock_db, limit=10, cursor=10)

        assert len(locations) == 2
        assert total == 100
        mock_query.filter.assert_called()

    def test_get_total_count(self, mock_db):
        mock_query = Mock()
        mock_query.scalar = Mock(return_value=500)
        mock_db.query = Mock(return_value=mock_query)

        result = location_svc.get_total_count(mock_db)

        assert result == 500

    def test_get_average_battery_24h_with_data(self, mock_db):
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.scalar = Mock(return_value=75.5)
        mock_db.query = Mock(return_value=mock_query)

        result = location_svc.get_average_battery_24h(mock_db)

        assert result == 75.5

    def test_get_average_battery_24h_no_data(self, mock_db):
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.scalar = Mock(return_value=None)
        mock_db.query = Mock(return_value=mock_query)

        result = location_svc.get_average_battery_24h(mock_db)

        assert result is None


class TestGeofenceService:
    """Tests for geofence service functions."""

    @pytest.fixture
    def mock_db(self):
        db = Mock(spec=Session)
        return db

    def test_create_geofence_success(self, mock_db):
        payload = {
            "name": "Test Fence",
            "latitude": -1.2921,
            "longitude": 36.8219,
            "radius_meters": 500,
        }
        mock_geofence = Geofence(id=1, **payload, is_active=True, created_at=datetime.utcnow())
        mock_db.add = Mock()
        mock_db.commit = Mock()
        mock_db.refresh = Mock()

        with patch.object(geofence_svc.Geofence, '__init__', return_value=None):
            with patch.object(geofence_svc, 'Geofence', return_value=mock_geofence):
                result = geofence_svc.create_geofence(mock_db, payload)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    def test_list_geofences_active_only(self, mock_db):
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.all = Mock(return_value=[
            Geofence(id=1, name="Fence1", latitude=-1.29, longitude=36.82, radius_meters=500, is_active=True),
        ])
        mock_db.query = Mock(return_value=mock_query)

        result = geofence_svc.list_geofences(mock_db)

        assert len(result) == 1
        assert result[0].is_active is True

    def test_delete_geofence_success(self, mock_db):
        mock_geofence = Geofence(
            id=1,
            name="ToDelete",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            is_active=True,
        )
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.first = Mock(return_value=mock_geofence)
        mock_db.query = Mock(return_value=mock_query)
        mock_db.commit = Mock()

        result = geofence_svc.delete_geofence(mock_db, 1)

        assert result == mock_geofence
        assert result.is_active is False
        mock_db.commit.assert_called()

    def test_delete_geofence_not_found(self, mock_db):
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.first = Mock(return_value=None)
        mock_db.query = Mock(return_value=mock_query)

        result = geofence_svc.delete_geofence(mock_db, 999)

        assert result is None

    def test_is_cooldown_active_no_previous_alert(self):
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=None,
        )

        result = geofence_svc.is_cooldown_active(geofence)

        assert result is False

    def test_is_cooldown_active_within_cooldown(self):
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=datetime.utcnow() - timedelta(minutes=10),
        )

        with patch.object(geofence_svc.settings, 'geofence_cooldown_minutes', 30):
            result = geofence_svc.is_cooldown_active(geofence)

        assert result is True

    def test_is_cooldown_active_expired(self):
        geofence = Geofence(
            id=1,
            name="Test",
            latitude=-1.29,
            longitude=36.82,
            radius_meters=500,
            last_alerted_at=datetime.utcnow() - timedelta(minutes=45),
        )

        with patch.object(geofence_svc.settings, 'geofence_cooldown_minutes', 30):
            result = geofence_svc.is_cooldown_active(geofence)

        assert result is False

    def test_get_active_count(self, mock_db):
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.scalar = Mock(return_value=5)
        mock_db.query = Mock(return_value=mock_query)

        result = geofence_svc.get_active_count(mock_db)

        assert result == 5

    def test_get_alerts_24h(self, mock_db):
        mock_query = Mock()
        mock_query.filter = Mock(return_value=mock_query)
        mock_query.scalar = Mock(return_value=12)
        mock_db.query = Mock(return_value=mock_query)

        result = geofence_svc.get_alerts_24h(mock_db)

        assert result == 12