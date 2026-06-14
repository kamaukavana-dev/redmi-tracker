"""
Rate limiting tests.

Tests rate limiting functionality on /track endpoint.
"""

import os
os.environ["TEST_MODE"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.config import settings
from app.models import Location, Geofence, Alert  # Import models to register with Base BEFORE create_all
from app.routers.track import _rate_limit_store

# Use StaticPool to ensure all connections share the same in-memory database
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


from fastapi import Request
from app.security import verify_api_key
import os

os.environ["TEST_RATE_LIMIT"] = "1"

def override_verify_api_key(request: Request):
    return request.headers.get("X-API-Key", "test_key")

@pytest.fixture(autouse=True)
def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_api_key] = override_verify_api_key
    Base.metadata.create_all(bind=engine)
    _rate_limit_store.clear()
    yield
    Base.metadata.drop_all(bind=engine)
    _rate_limit_store.clear()
    app.dependency_overrides.clear()


client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class TestRateLimiting:
    """Tests for rate limiting on /track endpoint."""

    def test_rate_limit_allows_under_limit_requests(self):
        """Requests under the limit should succeed."""
        for i in range(15):
            payload = {"latitude": -1.2921 + i * 0.0001, "longitude": 36.8219, "battery": 85}
            response = client.post("/track", json=payload, headers=HEADERS)
            assert response.status_code == 202

    def test_rate_limit_blocks_over_limit_requests(self):
        """Requests over the limit should return 429."""
        for i in range(20):
            payload = {"latitude": -1.2921 + i * 0.0001, "longitude": 36.8219, "battery": 85}
            response = client.post("/track", json=payload, headers=HEADERS)
            assert response.status_code == 202

        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)

        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert response.headers["Retry-After"] == "60"
        assert "Rate limit exceeded" in response.json()["error"]

    def test_rate_limit_per_api_key(self):
        """Rate limits should be per API key, not global."""
        _rate_limit_store.clear()

        headers1 = {"X-API-Key": "test_key_1"}
        headers2 = {"X-API-Key": "test_key_2"}

        for i in range(20):
            payload = {"latitude": -1.2921 + i * 0.0001, "longitude": 36.8219, "battery": 85}
            client.post("/track", json=payload, headers=headers1)

        response1 = client.post("/track", json=payload, headers=headers1)
        response2 = client.post("/track", json=payload, headers=headers2)

        assert response1.status_code == 429
        assert response2.status_code == 202

    def test_rate_limit_resets_after_window(self):
        """Rate limit should reset after time window passes."""
        from datetime import datetime, timedelta

        _rate_limit_store.clear()

        test_key = "test_key_window"
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=1)

        _rate_limit_store[test_key] = [window_start - timedelta(seconds=1)]

        from app.routers.track import check_rate_limit

        try:
            check_rate_limit(test_key)
        except Exception as e:
            pytest.fail(f"Should not raise exception after window reset: {e}")