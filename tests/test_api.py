"""
Comprehensive API endpoint tests.

Tests all endpoints for happy path, authentication failures, and edge cases.
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

TEST_DATABASE_URL = "sqlite:///./test.db"
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


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "timestamp" in data


class TestTrackEndpoint:
    """Tests for POST /track endpoint."""

    def test_track_location_success(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 201
        data = response.json()
        assert data["latitude"] == -1.2921
        assert data["longitude"] == 36.8219
        assert data["battery"] == 85
        assert "id" in data
        assert "recorded_at" in data

    def test_track_requires_api_key(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload)
        assert response.status_code == 403

    def test_track_invalid_api_key(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers={"X-API-Key": "wrong_key"})
        assert response.status_code == 403

    def test_track_invalid_latitude_high(self):
        payload = {"latitude": 91.0, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_track_invalid_latitude_low(self):
        payload = {"latitude": -91.0, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_track_invalid_longitude_high(self):
        payload = {"latitude": -1.2921, "longitude": 181.0, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_track_invalid_longitude_low(self):
        payload = {"latitude": -1.2921, "longitude": -181.0, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_track_invalid_battery_high(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 101}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_track_invalid_battery_low(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": -1}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_track_optional_battery(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 201
        data = response.json()
        assert data["battery"] is None

    def test_track_missing_required_fields(self):
        payload = {"latitude": -1.2921}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 422


class TestLocationLatestEndpoint:
    """Tests for GET /location/latest endpoint."""

    def test_get_latest_location_success(self):
        client.post("/track", json={"latitude": -1.2921, "longitude": 36.8219, "battery": 72}, headers=HEADERS)
        response = client.get("/location/latest", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["latitude"] == -1.2921
        assert data["battery"] == 72

    def test_get_latest_requires_api_key(self):
        response = client.get("/location/latest")
        assert response.status_code == 403

    def test_get_latest_no_data(self):
        response = client.get("/location/latest", headers=HEADERS)
        assert response.status_code == 404


class TestLocationHistoryEndpoint:
    """Tests for GET /location/history endpoint."""

    def test_get_history_success(self):
        for i in range(5):
            client.post("/track", json={"latitude": -1.29 + i * 0.01, "longitude": 36.82, "battery": 80}, headers=HEADERS)
        response = client.get("/location/history?limit=10", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 5
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 10
        assert "has_more" in data
        assert "next_cursor" in data

    def test_get_history_requires_api_key(self):
        response = client.get("/location/history")
        assert response.status_code == 403

    def test_get_history_pagination(self):
        for i in range(25):
            client.post("/track", json={"latitude": -1.29 + i * 0.001, "longitude": 36.82, "battery": 80}, headers=HEADERS)

        response1 = client.get("/location/history?limit=10", headers=HEADERS)
        data1 = response1.json()
        assert len(data1["data"]) == 10
        assert data1["has_more"] is True
        assert data1["next_cursor"] is not None

        response2 = client.get(f"/location/history?limit=10&cursor={data1['next_cursor']}", headers=HEADERS)
        data2 = response2.json()
        assert len(data2["data"]) == 10
        assert data2["page"] > data1["page"]

    def test_get_history_empty(self):
        response = client.get("/location/history", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["total"] == 0


class TestGeofenceEndpoint:
    """Tests for /geofence endpoints."""

    def test_create_geofence_success(self):
        payload = {"name": "Home", "latitude": -1.2921, "longitude": 36.8219, "radius_meters": 500}
        response = client.post("/geofence", json=payload, headers=HEADERS)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Home"
        assert data["latitude"] == -1.2921
        assert data["radius_meters"] == 500
        assert data["is_active"] is True

    def test_create_geofence_requires_api_key(self):
        payload = {"name": "Home", "latitude": -1.2921, "longitude": 36.8219, "radius_meters": 500}
        response = client.post("/geofence", json=payload)
        assert response.status_code == 403

    def test_create_geofence_invalid_radius(self):
        payload = {"name": "Home", "latitude": -1.2921, "longitude": 36.8219, "radius_meters": 0}
        response = client.post("/geofence", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_create_geofence_radius_too_large(self):
        payload = {"name": "Home", "latitude": -1.2921, "longitude": 36.8219, "radius_meters": 60000}
        response = client.post("/geofence", json=payload, headers=HEADERS)
        assert response.status_code == 422

    def test_list_geofences_success(self):
        payload = {"name": "Office", "latitude": -1.2800, "longitude": 36.8100, "radius_meters": 300}
        client.post("/geofence", json=payload, headers=HEADERS)
        response = client.get("/geofence", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Office"

    def test_list_geofences_requires_api_key(self):
        response = client.get("/geofence")
        assert response.status_code == 403

    def test_delete_geofence_success(self):
        create_resp = client.post("/geofence", json={"name": "ToDelete", "latitude": -1.29, "longitude": 36.82, "radius_meters": 100}, headers=HEADERS)
        geofence_id = create_resp.json()["id"]

        delete_resp = client.delete(f"/geofence/{geofence_id}", headers=HEADERS)
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "ok"

        list_resp = client.get("/geofence", headers=HEADERS)
        assert len(list_resp.json()) == 0

    def test_delete_geofence_not_found(self):
        response = client.delete("/geofence/99999", headers=HEADERS)
        assert response.status_code == 404

    def test_delete_geofence_requires_api_key(self):
        response = client.delete("/geofence/1")
        assert response.status_code == 403


class TestStatsEndpoint:
    """Tests for GET /stats endpoint."""

    def test_stats_success(self):
        response = client.get("/stats", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert "total_pings" in data
        assert "last_seen" in data
        assert "last_battery" in data
        assert "avg_battery_24h" in data
        assert "uptime_score" in data
        assert "geofences_active" in data
        assert "alerts_sent_24h" in data

    def test_stats_requires_api_key(self):
        response = client.get("/stats")
        assert response.status_code == 403

    def test_stats_with_data(self):
        client.post("/track", json={"latitude": -1.2921, "longitude": 36.8219, "battery": 85}, headers=HEADERS)
        client.post("/track", json={"latitude": -1.2922, "longitude": 36.8220, "battery": 84}, headers=HEADERS)

        response = client.get("/stats", headers=HEADERS)
        data = response.json()
        assert data["total_pings"] == 2
        assert data["last_battery"] == 84
        assert data["geofences_active"] == 0
        assert data["alerts_sent_24h"] == 0