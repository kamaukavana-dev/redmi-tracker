import os

with open('tests/test_cooldown.py', 'r') as f:
    content = f.read()

new_class = """class TestCooldownRaceConditions:
    \"\"\"Tests for race conditions in cooldown logic.\"\"\"

    @pytest.fixture
    def real_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        yield db
        db.close()

    def test_concurrent_breaches_same_geofence_single_alert(self, real_db):
        geofence = Geofence(name="Test Fence", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        real_db.add(geofence)
        real_db.commit()
        
        location1 = Location(latitude=-1.3000, longitude=36.8300, battery=85, recorded_at=datetime.utcnow())
        location2 = Location(latitude=-1.3001, longitude=36.8301, battery=84, recorded_at=datetime.utcnow() + timedelta(seconds=10))
        
        with patch.object(settings, 'geofence_cooldown_minutes', 30):
            alerts1 = check_all_geofences(real_db, location1)
            alerts2 = check_all_geofences(real_db, location2)

        assert len(alerts1) == 1
        assert len(alerts2) == 0

    def test_different_geofences_can_alert_simultaneously(self, real_db):
        g1 = Geofence(name="F1", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        g2 = Geofence(name="F2", latitude=-1.3000, longitude=36.8300, radius_meters=500, is_active=True)
        real_db.add_all([g1, g2])
        real_db.commit()

        location = Location(latitude=-1.3100, longitude=36.8400, battery=85, recorded_at=datetime.utcnow())
        with patch.object(settings, 'geofence_cooldown_minutes', 30):
            alerts = check_all_geofences(real_db, location)

        assert len(alerts) == 2

    def test_cooldown_prevents_rapid_successive_alerts(self, real_db):
        g = Geofence(name="Test", latitude=-1.2921, longitude=36.8219, radius_meters=500, is_active=True)
        real_db.add(g)
        real_db.commit()

        location = Location(latitude=-1.3000, longitude=36.8300, battery=85, recorded_at=datetime.utcnow())
        with patch.object(settings, 'geofence_cooldown_minutes', 30):
            alerts = []
            for _ in range(10):
                alerts.extend(check_all_geofences(real_db, location))

        assert len(alerts) == 1
"""

start_idx = content.find("class TestCooldownRaceConditions:")
content = content[:start_idx] + new_class

with open('tests/test_cooldown.py', 'w') as f:
    f.write(content)
