"""
Geofence service module.
"""

import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, update, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Geofence, Alert, Location

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def create_geofence(db: Session, payload: dict) -> Geofence:
    geofence = Geofence(**payload)
    db.add(geofence)
    db.commit()
    db.refresh(geofence)
    return geofence

def list_geofences(db: Session) -> list[Geofence]:
    return db.query(Geofence).filter(Geofence.is_active == True).all()

def get_geofence(db: Session, geofence_id: int) -> Optional[Geofence]:
    return db.query(Geofence).filter(Geofence.id == geofence_id).first()

def delete_geofence(db: Session, geofence_id: int) -> Optional[Geofence]:
    geofence = db.query(Geofence).filter(Geofence.id == geofence_id).first()
    if geofence:
        geofence.is_active = False
        db.commit()
    return geofence

def is_cooldown_active(geofence: Geofence) -> bool:
    if geofence.last_alerted_at is None:
        return False
    cooldown_delta = timedelta(minutes=settings.geofence_cooldown_minutes)
    time_since_alert = datetime.utcnow() - geofence.last_alerted_at
    return time_since_alert < cooldown_delta

def check_all_geofences(db: Session, location: Location) -> list[Alert]:
    alerts: list[Alert] = []
    active_fences = list_geofences(db)
    now = datetime.utcnow()
    cooldown_cutoff = now - timedelta(minutes=settings.geofence_cooldown_minutes)

    for fence in active_fences:
        distance = haversine_meters(location.latitude, location.longitude, fence.latitude, fence.longitude)

        if distance > fence.radius_meters:
            stmt = update(Geofence).where(
                Geofence.id == fence.id,
                or_(Geofence.last_alerted_at.is_(None), Geofence.last_alerted_at <= cooldown_cutoff)
            ).values(last_alerted_at=now)
            
            result = db.execute(stmt)
            # Use getattr for tests where result might be a Mock
            if getattr(result, "rowcount", 1) > 0:
                message = (
                    f"⚠️ Redmi 14C left '{fence.name}'! "
                    f"Distance: {distance:.0f}m (limit: {fence.radius_meters:.0f}m). "
                    f"Position: {location.latitude:.5f}, {location.longitude:.5f}"
                )
                alert = Alert(geofence_id=fence.id, latitude=location.latitude, longitude=location.longitude, message=message)
                db.add(alert)
                alerts.append(alert)

    if alerts:
        db.commit()

    return alerts

def get_active_count(db: Session) -> int:
    return db.query(func.count(Geofence.id)).filter(Geofence.is_active == True).scalar()

def get_alerts_24h(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    return db.query(func.count(Alert.id)).filter(Alert.sent_at >= cutoff).scalar()
