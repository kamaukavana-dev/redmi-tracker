"""
Geofence router module.

Handles geofence CRUD operations via POST, GET, DELETE endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import GeofenceCreate, GeofenceResponse, StatusResponse
from app.security import verify_api_key
from app.services import geofence as geofence_svc

router = APIRouter(prefix="/geofence", tags=["geofence"])


@router.post("", response_model=GeofenceResponse, status_code=201)
async def create_geofence(
    payload: GeofenceCreate,
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> GeofenceResponse:
    """
    Create a new geofence.

    Args:
        payload: Geofence data including name, coordinates, radius.
        db: Database session dependency.
        _: Validated API key from security dependency.

    Returns:
        Created geofence record with assigned ID.
    """
    return geofence_svc.create_geofence(db, payload.model_dump())


@router.get("", response_model=list[GeofenceResponse])
async def list_geofences(
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> list[GeofenceResponse]:
    """
    List all active geofences.

    Returns:
        List of active geofence records.
    """
    fences = geofence_svc.list_geofences(db)
    return [GeofenceResponse.model_validate(fence) for fence in fences]


@router.delete("/{geofence_id}", response_model=StatusResponse)
async def delete_geofence(
    geofence_id: int,
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> StatusResponse:
    """
    Deactivate a geofence.

    Args:
        geofence_id: Primary key of geofence to delete.
        db: Database session dependency.
        _: Validated API key from security dependency.

    Returns:
        Status response confirming deletion.

    Raises:
        HTTPException: 404 if geofence not found.
    """
    result = geofence_svc.delete_geofence(db, geofence_id)
    if not result:
        raise HTTPException(status_code=404, detail="Geofence not found.")
    return StatusResponse(status="ok", message="Geofence deactivated.")