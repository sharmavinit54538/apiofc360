"""Daily Face Attendance geofence verification router (/api/v1/attendance/geofence/*)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.schemas.face import GeofenceVerifyRequest, GeofenceVerifyResponse
from app.attendance.services.geofence_service import GeofenceService
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/geofence", tags=["Face Attendance Geofence"])


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> uuid.UUID:
    cid = claims.get("company_id")
    if not cid:
        raise AppException("Company context missing in user authentication claims.", status_code=403)
    return uuid.UUID(str(cid))


@router.post(
    "/verify",
    status_code=status.HTTP_200_OK,
    summary="Independently verify employee GPS coordinates against authorized office boundary",
)
async def verify_geofence(
    payload: GeofenceVerifyRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Calculates actual Haversine distance between employee coordinates and assigned office location.
    
    Backend independently verifies:
    - Never trusts frontend inside/outside assertions
    - Queries assigned office/branch from database
    - Rejects low or suspicious GPS accuracy
    """
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)

    repo = AttendanceRepository(db)
    employee = await repo.get_employee_by_user_id(user_id)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "EMPLOYEE_NOT_FOUND", "message": "Employee profile not found."},
        )

    service = GeofenceService(db)
    result = await service.verify_geofence(
        employee=employee,
        company_id=company_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        accuracy=payload.accuracy,
    )

    return {
        "success": True,
        "message": result["message"],
        "data": result,
        "error": None,
    }
