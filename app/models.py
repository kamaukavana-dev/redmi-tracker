"""
Database models module.

Defines SQLAlchemy ORM models for locations, geofences, and alerts.
All models inherit from Base and include appropriate indexes for performance.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Location(Base):
    """
    Location model storing device GPS coordinates and battery level.

    Enhanced for production-grade resilience with data quality tracking
    and raw payload preservation.
    """

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    battery: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    
    # Resilience fields
    data_quality: Mapped[str] = mapped_column(String(20), default="valid") # valid, degraded, invalid
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    recovered_fields: Mapped[Optional[str]] = mapped_column(String(500), nullable=True) # Comma separated list

    __table_args__ = (
        Index("ix_locations_recorded_at_desc", text("recorded_at DESC")),
        Index("ix_locations_lat_lon", "latitude", "longitude"),
        Index("ix_locations_quality", "data_quality"),
    )


class IngestionMetrics(Base):
    """
    Real-time counters for ingestion pipeline health.
    """
    __tablename__ = "ingestion_metrics"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)



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