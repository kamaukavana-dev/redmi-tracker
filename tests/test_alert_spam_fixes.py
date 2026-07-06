"""
Regression tests for the alert-spam post-mortem (panel audit).

Each test pins one of the mandated fixes so the spam bugs can never regress:

  Fix 1/5 — health alerts have independent 30-min cooldowns and are
            edge-triggered (fire once per episode, not every tick).
  Fix 2   — non-numeric coordinates ("Location Unknown") return HTTP 400.
  Fix 3   — a stale latest location is not used for geofence evaluation.
  Fix 4   — an identical Telegram message is suppressed within the window.
"""

import os
os.environ["TEST_MODE"] = "1"

from datetime import timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.config import settings
from app.models import Location, Geofence, HealthAlertState, NotificationLog
from app.services import geofence as geofence_svc
from app.services import alert_state
from app.utils.timeutils import now_utc

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
HEADERS = {"X-API-Key": settings.api_key}


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------------
# Fix 1 + 5 — health alert cooldown blocks repeat alerts
# --------------------------------------------------------------------------
class TestHealthAlertCooldown:
    def test_low_battery_and_gps_fire_once_over_many_ticks(self, db):
        """A stale, low-battery device must yield exactly ONE of each alert
        across many 5-minute ticks (was: one per tick — the spam bug)."""
        loc = Location(
            latitude=-1.29, longitude=36.82, battery=8,
            recorded_at=now_utc() - timedelta(minutes=45),
        )
        db.add(loc)
        db.commit()

        emitted = []
        for _ in range(12):  # one hour of 5-min ticks
            emitted.extend(
                a.event_type.value for a in geofence_svc.check_device_health(db, loc)
            )

        assert emitted.count("LOW_BATTERY") == 1
        assert emitted.count("GPS_SIGNAL_LOST") == 1

    def test_each_alert_type_has_independent_cooldown(self, db):
        """DEVICE_OFFLINE, LOW_BATTERY, GPS_SIGNAL_LOST cool down independently."""
        # First tick: all three conditions active -> all three fire.
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True) is True
        assert alert_state.should_send_health_alert(db, "GPS_SIGNAL_LOST", True) is True
        assert alert_state.should_send_health_alert(db, "DEVICE_OFFLINE", True) is True

        # Immediately after: every type is inside its own cooldown -> none fire.
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True) is False
        assert alert_state.should_send_health_alert(db, "GPS_SIGNAL_LOST", True) is False
        assert alert_state.should_send_health_alert(db, "DEVICE_OFFLINE", True) is False

    def test_cooldown_is_at_least_30_minutes(self, db):
        """A requested cooldown below 30 min is floored to 30 min."""
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True, cooldown_minutes=1) is True

        # 20 minutes later, still suppressed because the floor is 30 minutes.
        state = db.query(HealthAlertState).filter_by(alert_type="LOW_BATTERY").first()
        state.last_alerted_at = now_utc() - timedelta(minutes=20)
        db.commit()
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True, cooldown_minutes=1) is False

        # 31 minutes: cooldown expired AND condition re-armed -> fires again.
        state.last_alerted_at = now_utc() - timedelta(minutes=31)
        state.active = False  # condition cleared and returned (new episode)
        db.commit()
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True, cooldown_minutes=1) is True

    def test_recovery_rearms_edge_trigger(self, db):
        """When the condition clears then returns, a fresh alert may fire
        (subject to cooldown) — edge trigger re-arms."""
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True) is True
        # Condition clears (battery charged).
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", False) is False
        # Simulate cooldown elapsed, condition returns -> edge fires again.
        state = db.query(HealthAlertState).filter_by(alert_type="LOW_BATTERY").first()
        state.last_alerted_at = now_utc() - timedelta(minutes=31)
        db.commit()
        assert alert_state.should_send_health_alert(db, "LOW_BATTERY", True) is True

    def test_healthy_device_never_alerts(self, db):
        """A healthy, fresh device produces no health alerts."""
        loc = Location(latitude=-1.29, longitude=36.82, battery=95, recorded_at=now_utc())
        assert geofence_svc.check_device_health(db, loc) == []


# --------------------------------------------------------------------------
# Fix 2 — "Location Unknown" / non-numeric coordinates return 400
# --------------------------------------------------------------------------
class TestLocationUnknownRejected:
    @pytest.fixture(autouse=True)
    def _client(self):
        def override():
            s = TestingSessionLocal()
            try:
                yield s
            finally:
                s.close()
        app.dependency_overrides[get_db] = override
        yield
        app.dependency_overrides.clear()

    def test_location_unknown_returns_400(self):
        client = TestClient(app)
        r = client.post(
            "/track",
            json={"latitude": "Location Unknown", "longitude": "Location Unknown", "battery": 80},
            headers=HEADERS,
        )
        assert r.status_code == 400
        assert "not a numeric value" in r.json()["error"]

    def test_valid_string_coords_still_accepted(self):
        """Legitimate numeric strings remain accepted (zero-data-loss intact)."""
        client = TestClient(app)
        r = client.post(
            "/track",
            json={"latitude": "-1.2921", "longitude": "36.8219", "battery": 80},
            headers=HEADERS,
        )
        assert r.status_code == 202

    def test_missing_coords_still_absorbed(self):
        """Null/empty coordinates are still absorbed as degraded (not 400)."""
        client = TestClient(app)
        r = client.post(
            "/track",
            json={"latitude": None, "longitude": None, "battery": 80},
            headers=HEADERS,
        )
        assert r.status_code == 202
        assert r.json()["data_quality"] == "degraded"

    def test_rejection_logged_as_warning(self, caplog):
        import logging
        client = TestClient(app)
        with caplog.at_level(logging.WARNING, logger="app.routers.track"):
            client.post(
                "/track",
                json={"latitude": "Location Unknown", "longitude": "0"},
                headers=HEADERS,
            )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Rejected non-numeric coordinates" in r.message for r in warnings)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)


# --------------------------------------------------------------------------
# Fix 3 — stale location skips geofence evaluation
# --------------------------------------------------------------------------
class TestStaleLocationSkipsGeofence:
    @pytest.mark.asyncio
    async def test_stale_location_skips_evaluation(self):
        from app import scheduler
        db = TestingSessionLocal()
        stale = Location(
            latitude=-1.29, longitude=36.82, battery=80,
            recorded_at=now_utc() - timedelta(minutes=30),  # > 10-min threshold
        )
        db.add(stale)
        db.add(Geofence(name="Home", latitude=-1.29, longitude=36.82, radius_meters=500, is_active=True))
        db.commit()
        db.close()

        with patch("app.scheduler.SessionLocal", TestingSessionLocal), \
             patch("app.scheduler.send_telegram_with_retry", new=AsyncMock(return_value=True)), \
             patch.object(scheduler.geofence_state_svc, "check_all_geofences_stateful") as mock_eval, \
             patch("app.scheduler.logger") as mock_logger:
            await scheduler.check_geofences_job()

        mock_eval.assert_not_called()
        assert any("stale" in str(c).lower() for c in mock_logger.warning.call_args_list)

    @pytest.mark.asyncio
    async def test_fresh_location_is_evaluated(self):
        from app import scheduler
        db = TestingSessionLocal()
        fresh = Location(
            latitude=-1.29, longitude=36.82, battery=80,
            recorded_at=now_utc() - timedelta(minutes=2),  # within threshold
        )
        db.add(fresh)
        db.commit()
        db.close()

        with patch("app.scheduler.SessionLocal", TestingSessionLocal), \
             patch("app.scheduler.send_telegram_with_retry", new=AsyncMock(return_value=True)), \
             patch.object(scheduler.geofence_state_svc, "check_all_geofences_stateful", return_value=[]) as mock_eval, \
             patch.object(scheduler.geofence_svc, "check_device_health", return_value=[]):
            await scheduler.check_geofences_job()

        mock_eval.assert_called_once()


# --------------------------------------------------------------------------
# Fix 4 — duplicate Telegram message is suppressed
# --------------------------------------------------------------------------
class TestTelegramDeduplication:
    def test_identical_message_flagged_duplicate(self, db):
        msg = "🚨 EXIT\nGeofence: Home"
        assert alert_state.is_duplicate_message(db, msg) is False
        alert_state.record_sent_message(db, msg)
        assert alert_state.is_duplicate_message(db, msg) is True

    def test_different_messages_not_duplicate(self, db):
        alert_state.record_sent_message(db, "message A")
        assert alert_state.is_duplicate_message(db, "message B") is False

    def test_duplicate_expires_after_window(self, db):
        msg = "expiring message"
        alert_state.record_sent_message(db, msg)
        # Age the record beyond the 30-minute dedup window.
        row = db.query(NotificationLog).first()
        row.sent_at = now_utc() - timedelta(minutes=31)
        db.commit()
        assert alert_state.is_duplicate_message(db, msg) is False

    @pytest.mark.asyncio
    async def test_notifier_suppresses_second_identical_send(self):
        """End-to-end: the second identical send never reaches the Telegram API."""
        from app.services import notifier

        with patch("app.database.SessionLocal", TestingSessionLocal):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {"ok": True}
                resp.text = '{"ok": true}'
                mock_post.return_value = resp

                first = await notifier.send_telegram_with_retry("dedup-me")
                second = await notifier.send_telegram_with_retry("dedup-me")

        assert first is True
        assert second is True  # suppressed, reported as success
        assert mock_post.call_count == 1  # only ONE real send
