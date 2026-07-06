"""
MacroDroid compatibility tests.

Tests that the /track endpoint handles messy, real-world payloads
from MacroDroid and similar automation apps.
"""

import os
os.environ["TEST_MODE"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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


class TestMacroDroidPayloads:
    """Test MacroDroid-style messy payloads."""

    def test_string_coordinates(self):
        """MacroDroid often sends coordinates as strings."""
        payload = {"latitude": "-1.2921", "longitude": "36.8219", "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["data_quality"] == "valid"
        assert "latitude" in data["recovered_fields"]
        assert "longitude" in data["recovered_fields"]

    def test_empty_battery_string(self):
        """MacroDroid sends empty string for missing battery."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": ""}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["data_quality"] == "valid"

    def test_null_timestamp(self):
        """MacroDroid may send null timestamp."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85, "timestamp": None}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_all_empty_values(self):
        """All optional fields empty."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": "", "timestamp": ""}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_missing_battery_field(self):
        """Battery field completely missing."""
        payload = {"latitude": -1.2921, "longitude": 36.8219}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["data_quality"] == "valid"

    def test_missing_longitude(self):
        """Missing longitude - should be degraded."""
        payload = {"latitude": -1.2921, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"
        assert "Missing or invalid coordinates" in data["rejection_reason"]

    def test_missing_latitude(self):
        """Missing latitude - should be degraded."""
        payload = {"longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"
        assert "Missing or invalid coordinates" in data["rejection_reason"]

    def test_whitespace_in_values(self):
        """String values with whitespace."""
        payload = {"latitude": " -1.2921 ", "longitude": " 36.8219 ", "battery": " 85 "}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_float_battery(self):
        """Battery as float (unusual but possible)."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85.5}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_battery_as_string_number(self):
        """Battery as string number."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": "85"}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "battery" in data["recovered_fields"]


class TestHostilePayloads:
    """Test hostile/malformed payloads."""

    def test_completely_invalid_json(self):
        """Invalid JSON body."""
        response = client.post("/track", content=b"not json", headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "invalid"
        assert "JSON parse error" in data["rejection_reason"]

    def test_json_array_not_object(self):
        """JSON array instead of object."""
        response = client.post("/track", content=b"[1,2,3]", headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "invalid"

    def test_empty_object(self):
        """Empty JSON object."""
        response = client.post("/track", json={}, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"
        assert "Missing or invalid coordinates" in data["rejection_reason"]

    def test_coordinates_at_boundaries_valid(self):
        """Coordinates at exact boundaries."""
        payload = {"latitude": 90.0, "longitude": 180.0, "battery": 0}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "valid"

    def test_coordinates_just_outside_boundary(self):
        """Coordinates just outside boundaries."""
        payload = {"latitude": 90.1, "longitude": 180.1, "battery": 0}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["data_quality"] == "degraded"

    def test_negative_battery(self):
        """Negative battery value."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": -5}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_battery_over_100(self):
        """Battery over 100%."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 150}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_non_numeric_coordinates(self):
        """Non-numeric coordinate strings are rejected with 400 (panel Fix 2).

        A coordinate supplied as a non-numeric string (like MacroDroid's
        "Location Unknown") is a hard validation error, not absorbable data.
        """
        payload = {"latitude": "abc", "longitude": "xyz", "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 400
        data = response.json()
        assert "not a numeric value" in data["error"]


class TestNo422Errors:
    """Verify no 422 errors are returned for any payload."""

    def test_no_422_for_valid(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202

    def test_no_422_for_invalid_coords(self):
        payload = {"latitude": 999, "longitude": 999, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202

    def test_no_422_for_missing_fields(self):
        payload = {"latitude": -1.2921}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202

    def test_no_422_for_empty_strings(self):
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": ""}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202

    def test_no_422_for_null_values(self):
        payload = {"latitude": None, "longitude": None, "battery": None}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202

    def test_no_422_for_malformed_json(self):
        response = client.post("/track", content=b"{bad json}", headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202

    def test_no_422_for_wrong_types(self):
        payload = {"latitude": True, "longitude": False, "battery": []}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code != 422
        assert response.status_code == 202