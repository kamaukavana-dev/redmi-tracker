"""
Pydantic schemas module.

Defines request/response schemas for API validation and serialization.
All schemas follow Pydantic v2 conventions with model_config.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LocationCreate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    battery: Optional[int] = Field(None, ge=0, le=100)
    timestamp: Optional[int] = None

    @field_validator("latitude", "longitude", "battery", "timestamp", mode="before")
    @classmethod
    def strip_whitespace(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class LocationResponse(BaseModel):
    """
    Schema for location response data.

    Used for GET endpoints returning location information.
    """

    id: int
    latitude: float
    longitude: float
    battery: Optional[int]
    recorded_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class LocationHistoryResponse(BaseModel):
    """
    Schema for paginated location history response.

    Includes pagination metadata for cursor-based navigation.
    """

    data: list[LocationResponse]
    total: int
    page: int
    per_page: int
    next_cursor: Optional[int]
    has_more: bool


class GeofenceCreate(BaseModel):
    """
    Schema for creating a new geofence.

    Used for POST /geofence endpoint request body validation.
    """

    name: str = Field(..., min_length=1, max_length=100, description="Geofence name")
    latitude: float = Field(..., ge=-90, le=90, description="Center latitude")
    longitude: float = Field(..., ge=-180, le=180, description="Center longitude")
    radius_meters: float = Field(..., gt=0, le=50000, description="Radius in meters (1-50000)")


class GeofenceResponse(BaseModel):
    """
    Schema for geofence response data.

    Used for GET endpoints returning geofence information.
    """

    id: int
    name: str
    latitude: float
    longitude: float
    radius_meters: float
    is_active: bool
    created_at: datetime
    last_alerted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AlertResponse(BaseModel):
    """
    Schema for alert response data.

    Used for endpoints returning alert information.
    """

    id: int
    geofence_id: int
    latitude: float
    longitude: float
    message: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class StatusResponse(BaseModel):
    """
    Generic status response schema.

    Used for simple success/failure endpoints.
    """

    status: str
    message: str


class ErrorResponse(BaseModel):
    error: str
    code: int
    path: str
    request_id: str
    timestamp: datetime


class Position(BaseModel):
    latitude: float
    longitude: float

class StatsResponse(BaseModel):
    total_pings: int
    last_seen: Optional[datetime]
    last_known_position: Optional[Position]
    last_battery: Optional[int]
    avg_battery_24h: Optional[float]
    uptime_score: float
    uptime_score_24h: float
    geofences_active: int
    alerts_sent_24h: int
    pings_last_hour: int


class HealthResponse(BaseModel):
    """
    Schema for health check endpoint.

    Includes status of all critical dependencies.
    """

    status: str
    database: bool
    telegram: bool
    timestamp: datetime
