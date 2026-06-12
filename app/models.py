"""
Database models module.

Defines SQLAlchemy ORM models for locations, geofences, and alerts.
All models inherit from Base and include appropriate indexes for performance.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Location(Base):
    """
    Location model storing device GPS coordinates and battery level.

    Each record represents a single ping from the tracked device.
    Locations are stored chronologically and queried for history and analysis.

    Attributes:
        id: Primary key identifier.
        latitude: GPS latitude coordinate (-90 to 90).
        longitude: GPS longitude coordinate (-180 to 180).
        battery: Battery percentage (0-100), nullable.
        recorded_at: Timestamp when location was recorded by device.
        created_at: Timestamp when record was created in database.
    """

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    battery: Mapped[int] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_locations_recorded_at_desc", text("recorded_at DESC")),
        Index("ix_locations_lat_lon", "latitude", "longitude"),
    )


class Geofence(Base):
    """
    Geofence model defining circular geographic boundaries for alerts.

    Geofences are used to monitor when the tracked device enters or leaves
    specified areas. Alerts are triggered on boundary violations.

    Attributes:
        id: Primary key identifier.
        name: Human-readable name for the geofence.
        latitude: Center point latitude.
        longitude: Center point longitude.
        radius_meters: Radius of the circular boundary in meters.
        is_active: Whether the geofence is currently monitored.
        created_at: Timestamp when geofence was created.
        last_alerted_at: Timestamp of last alert for cooldown tracking.
        alerts: Relationship to Alert records.
    """

    __tablename__ = "geofences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_meters: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_alerted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="geofence")


class Alert(Base):
    """
    Alert model recording geofence boundary violations.

    Each alert represents a single geofence breach event with location
    details and notification status.

    Attributes:
        id: Primary key identifier.
        geofence_id: Foreign key to the violated geofence.
        latitude: Device latitude at time of breach.
        longitude: Device longitude at time of breach.
        message: Alert message sent to Telegram.
        sent_at: Timestamp when alert was generated.
        geofence: Relationship to parent Geofence.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    geofence_id: Mapped[int] = mapped_column(Integer, ForeignKey("geofences.id"))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    geofence: Mapped["Geofence"] = relationship("Geofence", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_geofence_id_sent_at_desc", "geofence_id", text("sent_at DESC")),
    )