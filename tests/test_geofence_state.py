"""
Tests for geofence state machine.

Covers:
- State transitions
- Alert generation on valid transitions
- Cooldown protection
- State persistence
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.database import Base
from app.models import Location, Geofence, Alert
from app.services import geofence_state as state_svc
from app.services.geofence_state import GeofenceState, StateTransition


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
    session.query(Alert).delete()
    session.query(Geofence).delete()
    session.commit()
    yield session
    session.rollback()
    session.close()


class TestStateEvaluation:
    """Test state evaluation logic."""

    def test_evaluate_state_inside(self, db_session: Session):
        """Test evaluation when device is inside geofence."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=1000,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, location, None, None
        )

        assert current_state == GeofenceState.INSIDE
        assert transition == StateTransition.UNKNOWN_TO_INSIDE

    def test_evaluate_state_outside(self, db_session: Session):
        """Test evaluation when device is outside geofence."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=100,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.01,
            longitude=0.01,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, location, None, None
        )

        assert current_state == GeofenceState.OUTSIDE
        assert transition == StateTransition.UNKNOWN_TO_OUTSIDE
        assert should_alert == True

    def test_evaluate_state_offline(self, db_session: Session):
        """Test evaluation when device is offline."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=1000,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow() - timedelta(hours=2),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, location, None, None
        )

        assert current_state == GeofenceState.OFFLINE


class TestStateTransitions:
    """Test state transition logic."""

    def test_inside_to_outside_transition(self, db_session: Session):
        """Test transition from inside to outside."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=500,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        inside_loc = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow() - timedelta(minutes=5),
        )
        db_session.add(inside_loc)
        db_session.commit()

        outside_loc = Location(
            latitude=0.01,
            longitude=0.01,
            battery=79,
            recorded_at=datetime.utcnow(),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, outside_loc, GeofenceState.INSIDE, None
        )

        assert current_state == GeofenceState.OUTSIDE
        assert transition == StateTransition.INSIDE_TO_OUTSIDE
        assert should_alert == True

    def test_no_transition_same_state(self, db_session: Session):
        """Test no transition when state doesn't change."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=1000,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, location, GeofenceState.INSIDE, None
        )

        assert current_state == GeofenceState.INSIDE
        assert transition == StateTransition.NO_CHANGE
        assert should_alert == False


class TestCooldownProtection:
    """Test cooldown protection logic."""

    def test_cooldown_blocks_repeat_alert(self, db_session: Session):
        """Test that cooldown prevents duplicate alerts."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=100,
            is_active=True,
            last_alerted_at=datetime.utcnow(),
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.01,
            longitude=0.01,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, location, GeofenceState.INSIDE, geofence.last_alerted_at
        )

        assert current_state == GeofenceState.OUTSIDE
        assert transition == StateTransition.INSIDE_TO_OUTSIDE
        assert should_alert == False

    def test_cooldown_expired_allows_alert(self, db_session: Session):
        """Test that expired cooldown allows new alert."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=100,
            is_active=True,
            last_alerted_at=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.01,
            longitude=0.01,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        current_state, transition, should_alert = state_svc.evaluate_geofence_state(
            geofence, location, GeofenceState.INSIDE, geofence.last_alerted_at
        )

        assert current_state == GeofenceState.OUTSIDE
        assert transition == StateTransition.INSIDE_TO_OUTSIDE
        assert should_alert == True


class TestStatefulGeofenceCheck:
    """Test stateful geofence checking."""

    def test_stateful_check_with_null_coordinates(self, db_session: Session):
        """Test stateful check handles null coordinates."""
        location = Location(
            latitude=None,
            longitude=None,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        alerts = state_svc.check_all_geofences_stateful(db_session, location)
        assert len(alerts) == 0

    def test_stateful_check_generates_alerts(self, db_session: Session):
        """Test stateful check generates alerts on breach."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=100,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.01,
            longitude=0.01,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        alerts = state_svc.check_all_geofences_stateful(db_session, location)
        
        assert len(alerts) > 0
        assert alerts[0].event_type.value in ["EXIT", "EXITED_GEOFENCE"]

    def test_stateful_check_no_alerts_inside(self, db_session: Session):
        """Test stateful check no alerts when inside."""
        geofence = Geofence(
            name="Test Fence",
            latitude=0.0,
            longitude=0.0,
            radius_meters=1000,
            is_active=True,
        )
        db_session.add(geofence)
        db_session.commit()

        location = Location(
            latitude=0.0,
            longitude=0.0,
            battery=80,
            recorded_at=datetime.utcnow(),
        )

        alerts = state_svc.check_all_geofences_stateful(db_session, location)
        assert len(alerts) == 0


class TestStateMachineDiagram:
    """Test state machine diagram generation."""

    def test_diagram_generation(self):
        """Test that diagram can be generated."""
        diagram = state_svc.get_state_machine_diagram()
        assert isinstance(diagram, str)
        assert len(diagram) > 100
        assert "GEOFENCE STATE MACHINE" in diagram
        assert "UNKNOWN" in diagram
        assert "INSIDE" in diagram
        assert "OUTSIDE" in diagram
        assert "OFFLINE" in diagram