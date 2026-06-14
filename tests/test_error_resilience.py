"""
Error resilience tests.

Verifies that all endpoints handle errors gracefully and return
structured JSON responses without crashing.
"""

import os
os.environ["TEST_MODE"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.config import settings
from app.models import Location

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
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
    from app.routers.track import _rate_limit_store
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    _rate_limit_store.clear()
    yield
    Base.metadata.drop_all(bind=engine)
    _rate_limit_store.clear()
    app.dependency_overrides.clear()


class TestTrackErrorResilience:
    """Test /track endpoint error handling."""

    def test_garbage_json_returns_202_not_500(self):
        """Completely invalid JSON should be handled gracefully."""
        response = client.post("/track", content=b"{{{{{", headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "invalid"

    def test_empty_body_returns_202(self):
        """Empty body should be handled gracefully."""
        response = client.post("/track", content=b"", headers=HEADERS)
        assert response.status_code == 202

    def test_unicode_garbage_handled(self):
        """Unicode garbage should be handled."""
        response = client.post("/track", content="你好世界".encode("utf-8"), headers=HEADERS)
        assert response.status_code == 202

    def test_null_coordinates_handled(self):
        """Null coordinates should not crash."""
        payload = {"latitude": None, "longitude": None}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"

    def test_boolean_coordinates_handled(self):
        """Boolean coordinates should be handled gracefully."""
        payload = {"latitude": True, "longitude": False}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202

    def test_array_coordinates_handled(self):
        """Array coordinates should be handled gracefully."""
        payload = {"latitude": [1, 2], "longitude": [3, 4]}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"

    def test_object_coordinates_handled(self):
        """Object coordinates should be handled gracefully."""
        payload = {"latitude": {"a": 1}, "longitude": {"b": 2}}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"


class TestLocationEndpointsErrorResilience:
    """Test /location endpoints error handling."""

    def test_latest_returns_404_no_data(self):
        """GET /location/latest with no data returns 404."""
        response = client.get("/location/latest", headers=HEADERS)
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    def test_history_returns_empty_list(self):
        """GET /location/history with no data returns empty list."""
        response = client.get("/location/history", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["total"] == 0


class TestGeofenceEndpointsErrorResilience:
    """Test /geofence endpoints error handling."""

    def test_delete_nonexistent_returns_404(self):
        """DELETE /geofence/999 returns 404."""
        response = client.delete("/geofence/999", headers=HEADERS)
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    def test_create_with_invalid_data_returns_422(self):
        """POST /geofence with invalid data returns 422."""
        payload = {"name": "", "latitude": 999, "longitude": 999, "radius_meters": -1}
        response = client.post("/geofence", json=payload, headers=HEADERS)
        assert response.status_code == 422


class TestStatsEndpointErrorResilience:
    """Test /stats endpoint error handling."""

    def test_stats_never_crashes(self):
        """GET /stats should never crash."""
        response = client.get("/stats", headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert "total_pings" in data


class TestHealthEndpointErrorResilience:
    """Test /health endpoint error handling."""

    def test_health_always_returns(self):
        """GET /health should always return."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "timestamp" in data


class TestStructuredErrorResponses:
    """Verify all errors return structured JSON."""

    def test_403_has_error_field(self):
        """403 responses should have structured error."""
        response = client.post("/track", json={"latitude": 1, "longitude": 1})
        assert response.status_code == 403
        data = response.json()
        assert "error" in data or "detail" in data

    def test_404_has_error_field(self):
        """404 responses should have structured error."""
        response = client.get("/location/latest", headers=HEADERS)
        assert response.status_code == 404
        data = response.json()
        assert "error" in data


class TestNoUncaughtExceptions:
    """Verify no uncaught exceptions crash the app."""

    def test_malformed_utf8_handled(self):
        """Malformed UTF-8 should be handled."""
        response = client.post("/track", content=b"\xff\xfe", headers=HEADERS)
        assert response.status_code == 202

    def test_very_long_payload_handled(self):
        """Very long payload should be handled."""
        long_string = "x" * 100000
        payload = {"latitude": long_string, "longitude": long_string}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"

    def test_deeply_nested_json_handled(self):
        """Deeply nested JSON should be handled."""
        payload = {"latitude": {"a": {"b": {"c": 1}}}, "longitude": 36.8219}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"