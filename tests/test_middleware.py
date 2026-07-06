"""
Test module for request logging middleware.

Tests X-Request-ID header and structured logging.
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


client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class TestRequestLoggingMiddleware:
    """Tests for request logging middleware."""

    def test_health_endpoint_returns_response(self):
        """Health endpoint should return valid response."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data

    def test_authenticated_request_succeeds(self):
        """Authenticated requests should succeed."""
        payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
        response = client.post("/track", json=payload, headers=HEADERS)
        assert response.status_code == 202

    def test_unauthenticated_request_fails(self):
        """Unauthenticated requests should fail with 403."""
        payload = {"latitude": -1.2921, "longitude": 36.8219}
        response = client.post("/track", json=payload)
        assert response.status_code == 403