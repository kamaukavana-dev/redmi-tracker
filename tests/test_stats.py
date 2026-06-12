"""
Test module for stats endpoint.

Tests all fields and edge cases for GET /stats endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from app.main import app
from app.database import Base, get_db
from app.config import settings
from app.models import Location, Geofence, Alert

TEST_DATABASE_URL = "sqlite:///./test_stats.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestStatsEndpoint:
    """Tests for GET /stats endpoint."""

    def test_stats_empty_state(self):
        """Stats should return zeros when no data exists."""
        response = client.get("/stats", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_pings"] == 0
        assert data["last_seen"] is None
        assert data["last_battery"] is None
        assert data["avg_battery_24h"] is None
        assert data["uptime_score"] == 0.0
        assert data["geofences_active"] == 0
        assert data["alerts_sent_24h"] == 0

    def test_stats_with_locations(self):
        """Stats should reflect location data."""
        now = datetime.utcnow()
        
        db = TestingSessionLocal()
        loc1 = Location(latitude=-1.2921, longitude=36.8219, battery=85, recorded_at=now)
        loc2 = Location(latitude=-1.2922, longitude=36.8220, battery=80, recorded_at=now - timedelta(hours=1))
        db.add_all([loc1, loc2])
        db.commit()
        db.close()

        response = client.get("/stats", headers=HEADERS)
        data = response.json()
        
        assert data["total_pings"] == 2
        assert data["last_battery"] == 85
        assert data["geofences_active"] == 0

    def test_stats_with_geofences(self):
        """Stats should count active geofences."""
        db = TestingSessionLocal()
        fence = Geofence(
            name="Test Fence",
            latitude=-1.2921,
            longitude=36.8219,
            radius_meters=500,
            is_active=True,
        )
        db.add(fence)
        db.commit()
        db.close()

        response = client.get("/stats", headers=HEADERS)
        data = response.json()
        
        assert data["geofences_active"] == 1

    def test_stats_with_alerts(self):
        """Stats should count recent alerts."""
        db = TestingSessionLocal()
        fence = Geofence(
            name="Test",
            latitude=-1.2921,
            longitude=36.8219,
            radius_meters=500,
            is_active=True,
        )
        db.add(fence)
        db.commit()
        db.refresh(fence)
        alert = Alert(
            geofence_id=fence.id,
            latitude=-1.3000,
            longitude=36.8300,
            message="Test alert",
            sent_at=datetime.utcnow(),
        )
        db.add(alert)
        db.commit()
        db.close()

        response = client.get("/stats", headers=HEADERS)
        data = response.json()
        
        assert data["alerts_sent_24h"] == 1

    def test_stats_requires_api_key(self):
        """Stats endpoint should require authentication."""
        response = client.get("/stats")
        assert response.status_code == 403

    def test_stats_all_fields_present(self):
        """Stats response should have all required fields."""
        response = client.get("/stats", headers=HEADERS)
        data = response.json()
        
        required_fields = [
            "total_pings",
            "last_seen",
            "last_battery",
            "avg_battery_24h",
            "uptime_score",
            "geofences_active",
            "alerts_sent_24h",
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"