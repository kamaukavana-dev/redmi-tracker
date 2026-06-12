"""
Location service module.

Handles location data ingestion, retrieval, and history queries.
All functions are synchronous and expect an active database session.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Location
from app.schemas import LocationCreate


def ingest_location(db: Session, payload: LocationCreate) -> Location:
    """
    Ingest a new location record into the database.

    Args:
        db: Active SQLAlchemy session.
        payload: Validated location data from API request.

    Returns:
        The created Location record with generated ID.
    """
    location = Location(
        latitude=payload.latitude,
        longitude=payload.longitude,
        battery=payload.battery,
        recorded_at=datetime.utcnow(),
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def get_latest(db: Session) -> Optional[Location]:
    """
    Retrieve the most recent location record.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        The most recent Location record, or None if no records exist.
    """
    return db.query(Location).order_by(Location.recorded_at.desc()).first()


def get_history(
    db: Session,
    limit: int = 100,
    cursor: Optional[int] = None,
) -> tuple[list[Location], Optional[int], int]:
    """
    Retrieve location history with cursor-based pagination.

    Args:
        db: Active SQLAlchemy session.
        limit: Maximum number of records to return (default 100).
        cursor: ID of last seen record for pagination (None for first page).

    Returns:
        Tuple of (locations list, next cursor ID or None, total count).
    """
    total = db.query(func.count(Location.id)).scalar()

    query = db.query(Location).order_by(Location.id.desc())

    if cursor is not None:
        query = query.filter(Location.id < cursor)

    locations = query.limit(limit + 1).all()

    has_more = len(locations) > limit
    if has_more:
        locations = locations[:limit]

    next_cursor = locations[-1].id if locations and has_more else None

    return locations, next_cursor, total


def get_locations_24h(db: Session) -> list[Location]:
    """
    Retrieve all locations from the last 24 hours.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        List of Location records from last 24 hours.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    return db.query(Location).filter(Location.recorded_at >= cutoff).all()


def get_total_count(db: Session) -> int:
    """
    Get total count of all location records.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Total number of Location records in database.
    """
    return db.query(func.count(Location.id)).scalar()


def get_average_battery_24h(db: Session) -> Optional[float]:
    """
    Calculate average battery level over last 24 hours.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Average battery percentage, or None if no data available.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    result = db.query(func.avg(Location.battery)).filter(
        Location.recorded_at >= cutoff,
        Location.battery.isnot(None),
    ).scalar()

    return float(result) if result is not None else None
def get_pings_last_hour(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=1)
    return db.query(func.count(Location.id)).filter(Location.recorded_at >= cutoff).scalar()
