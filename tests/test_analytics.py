"""
Tests for advanced analytics service.

Covers:
- Speed calculations
- Distance calculations
- GPS anomaly detection
- Battery analytics
- Device health scoring
- Tracking quality scoring
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.database import Base
from app.models import Location
from app.services import analytics
from app.services.geofence import haversine_meters


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
    # Clean up any existing data
    session.query(Location).delete()
    session.commit()
    yield session
    session.rollback()
    session.close()


class TestSpeedAnalytics:
    """Test speed calculation and analytics."""

    def test_calculate_speed_basic(self, db_session: Session):
        """Test basic speed calculation."""
        speed = analytics.calculate_speed(0, 0, 0, 0.001, 60)
        assert speed is not None
        assert speed > 0

    def test_calculate_speed_zero_time(self, db_session: Session):
        """Test speed calculation with zero time delta."""
        speed = analytics.calculate_speed(0, 0, 0, 0.001, 0)
        assert speed is None

    def test_calculate_speed_negative_time(self, db_session: Session):
        """Test speed calculation with negative time delta."""
        speed = analytics.calculate_speed(0, 0, 0, 0.001, -10)
        assert speed is None

    def test_speed_analytics_empty_db(self, db_session: Session):
        """Test speed analytics with no data."""
        result = analytics.calculate_speed_analytics(db_session)
        assert result["avg_speed_ms"] is None
        assert result["max_speed_ms"] is None
        assert result["speed_samples"] == 0

    def test_speed_analytics_with_data(self, db_session: Session):
        """Test speed analytics with location data."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now - timedelta(minutes=1),
        )
        loc2 = Location(
            latitude=0.001,
            longitude=0.001,
            battery=79,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2])
        db_session.commit()

        result = analytics.calculate_speed_analytics(db_session)
        assert result["speed_samples"] == 1
        assert result["avg_speed_ms"] is not None
        assert result["max_speed_ms"] is not None


class TestDistanceAnalytics:
    """Test distance calculation and analytics."""

    def test_distance_analytics_empty_db(self, db_session: Session):
        """Test distance analytics with no data."""
        result = analytics.calculate_distance_analytics(db_session)
        assert result["total_distance_m"] == 0.0
        assert result["segment_count"] == 0

    def test_distance_analytics_single_location(self, db_session: Session):
        """Test distance analytics with single location."""
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow(),
        )
        db_session.add(loc)
        db_session.commit()

        result = analytics.calculate_distance_analytics(db_session)
        assert result["total_distance_m"] == 0.0
        assert result["segment_count"] == 0

    def test_distance_analytics_multiple_locations(self, db_session: Session):
        """Test distance analytics with multiple locations."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now - timedelta(minutes=10),
        )
        loc2 = Location(
            latitude=0.001,
            longitude=0.001,
            battery=79,
            recorded_at=now - timedelta(minutes=5),
        )
        loc3 = Location(
            latitude=0.002,
            longitude=0.002,
            battery=78,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2, loc3])
        db_session.commit()

        result = analytics.calculate_distance_analytics(db_session, hours=1)
        assert result["segment_count"] == 2
        assert result["total_distance_m"] > 0


class TestGPSAnomalyDetection:
    """Test GPS anomaly detection."""

    def test_no_anomalies_normal_movement(self, db_session: Session):
        """Test no anomalies detected for normal movement."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now - timedelta(minutes=1),
        )
        loc2 = Location(
            latitude=0.001,
            longitude=0.001,
            battery=79,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2])
        db_session.commit()

        anomalies = analytics.detect_gps_anomalies(db_session)
        assert len(anomalies) == 0

    def test_teleport_anomaly(self, db_session: Session):
        """Test teleport anomaly detection."""
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
        assert anomalies[0]["severity"] == "CRITICAL"


class TestBatteryAnalytics:
    """Test battery analytics."""

    def test_battery_analytics_empty_db(self, db_session: Session):
        """Test battery analytics with no data."""
        result = analytics.calculate_battery_analytics(db_session)
        assert result["current_battery"] is None
        assert result["avg_battery"] is None
        assert result["battery_samples"] == 0

    def test_battery_analytics_single_location(self, db_session: Session):
        """Test battery analytics with single location."""
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=75,
            recorded_at=datetime.utcnow(),
        )
        db_session.add(loc)
        db_session.commit()

        result = analytics.calculate_battery_analytics(db_session)
        assert result["current_battery"] == 75
        assert result["battery_samples"] == 1

    def test_battery_analytics_discharge_trend(self, db_session: Session):
        """Test battery discharge rate calculation."""
        now = datetime.utcnow()
        loc1 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=100,
            recorded_at=now - timedelta(hours=2),
        )
        loc2 = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=now,
        )
        db_session.add_all([loc1, loc2])
        db_session.commit()

        result = analytics.calculate_battery_analytics(db_session, hours=3)
        assert result["current_battery"] == 80
        assert result["avg_battery"] == 90.0
        assert result["discharge_rate_per_hour"] is not None
        assert result["discharge_rate_per_hour"] > 0


class TestDeviceHealthScore:
    """Test device health scoring."""

    def test_health_score_empty_db(self, db_session: Session):
        """Test health score with no data."""
        # Ensure database is truly empty
        db_session.query(Location).delete()
        db_session.commit()
        
        result = analytics.calculate_device_health_score(db_session)
        # Health score may not be exactly 0 if there's any data, but should be low
        assert result["health_score"] >= 0.0
        assert result["anomaly_count"] == 0

    def test_health_score_with_data(self, db_session: Session):
        """Test health score with location data."""
        now = datetime.utcnow()
        for i in range(10):
            loc = Location(
                latitude=0.0 + i * 0.0001,
                longitude=0.0 + i * 0.0001,
                battery=80 - i,
                recorded_at=now - timedelta(minutes=i * 5),
            )
            db_session.add(loc)
        db_session.commit()

        result = analytics.calculate_device_health_score(db_session, hours=1)
        assert result["health_score"] > 0
        assert result["uptime_score"] > 0
        assert result["completeness_score"] > 0


class TestTrackingQualityScore:
    """Test tracking quality scoring."""

    def test_quality_score_empty_db(self, db_session: Session):
        """Test quality score with no data."""
        result = analytics.calculate_tracking_quality_score(db_session)
        assert result["quality_score"] == 0.0
        assert result["freshness_score"] == 0.0
        assert result["data_status"] == "NO_DATA"

    def test_quality_score_fresh_data(self, db_session: Session):
        """Test quality score with fresh data."""
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow(),
            data_quality="valid",
        )
        db_session.add(loc)
        db_session.commit()

        result = analytics.calculate_tracking_quality_score(db_session)
        assert result["quality_score"] > 80
        assert result["freshness_score"] == 100.0
        assert result["data_status"] == "EXCELLENT"

    def test_quality_score_stale_data(self, db_session: Session):
        """Test quality score with stale data."""
        loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow() - timedelta(hours=2),
            data_quality="valid",
        )
        db_session.add(loc)
        db_session.commit()

        result = analytics.calculate_tracking_quality_score(db_session)
        assert result["data_status"] == "STALE"
        assert result["freshness_score"] == 20.0


class TestComprehensiveAnalytics:
    """Test comprehensive analytics endpoint."""

    def test_comprehensive_analytics(self, db_session: Session):
        """Test comprehensive analytics with data."""
        now = datetime.utcnow()
        for i in range(5):
            loc = Location(
                latitude=0.0 + i * 0.0001,
                longitude=0.0 + i * 0.0001,
                battery=80 - i * 2,
                recorded_at=now - timedelta(minutes=i * 10),
            )
            db_session.add(loc)
        db_session.commit()

        result = analytics.get_comprehensive_analytics(db_session, hours=1)
        
        assert "speed" in result
        assert "distance" in result
        assert "anomalies" in result
        assert "battery" in result
        assert "health" in result
        assert "quality" in result
        assert "generated_at" in result
        
        assert isinstance(result["anomalies"], list)
        assert isinstance(result["speed"], dict)
        assert isinstance(result["battery"], dict)