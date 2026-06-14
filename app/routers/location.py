"""
Location router module.

Handles location data retrieval via GET endpoints.
Implements cursor-based pagination for history endpoint.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import LocationResponse, LocationHistoryResponse
from app.security import verify_api_key
from app.services import location as location_svc

router = APIRouter(prefix="/location", tags=["location"])


@router.get("/latest", response_model=LocationResponse)
async def get_latest(
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> LocationResponse:
    """
    Get the most recent location record.

    Returns:
        The latest location with all fields.

    Raises:
        HTTPException: 404 if no location data exists.
    """
    location = location_svc.get_latest(db)
    if not location:
        raise HTTPException(status_code=404, detail="No location data yet.")
    return location


@router.get("/history", response_model=LocationHistoryResponse)
async def get_history(
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: Optional[int] = Query(default=None, description="Pagination cursor (last seen ID)"),
    db: Session = Depends(get_db),
    _: str = Security(verify_api_key),
) -> LocationHistoryResponse:
    """
    Get location history with cursor-based pagination.

    Query Parameters:
        limit: Number of records to return (1-1000, default 100).
        cursor: ID of last seen record for pagination.

    Returns:
        Paginated response with data, total, page info, and next cursor.
    """
    locations, next_cursor, total = location_svc.get_history(db, limit, cursor)

    page = 1 if cursor is None else (cursor // limit) + 1

    return LocationHistoryResponse(
        data=[LocationResponse.model_validate(loc) for loc in locations],
        total=total,
        page=page,
        per_page=limit,
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )