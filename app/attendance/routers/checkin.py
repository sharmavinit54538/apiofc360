"""Daily Face Attendance check-in controller route."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.attendance.schemas.response import AttendanceResponse
from app.attendance.services.checkin_service import AttendanceCheckInService

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise AppException(
            message="Company context missing in user authentication claims.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return uuid.UUID(company_id_str)


@router.post(
    "/face/check-in",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AttendanceResponse],
    summary="Record daily attendance check-in with a face photograph",
)
async def face_check_in(
    file: UploadFile = File(..., description="Captured face image proof"),
    latitude: Optional[float] = Form(None, description="Check-in latitude coordinates"),
    longitude: Optional[float] = Form(None, description="Check-in longitude coordinates"),
    device_info: Optional[str] = Form(None, description="IP/device description info string"),
    ip_address: Optional[str] = Form(None, description="Requesting network IP address"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[AttendanceResponse]:
    """Record daily check-in with location and device metadata."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    
    service = AttendanceCheckInService(db)
    record = await service.check_in(
        user_id=user_id,
        company_id=company_id,
        file=file,
        latitude=latitude,
        longitude=longitude,
        device_info=device_info,
        ip_address=ip_address,
    )
    
    return APIResponse[AttendanceResponse](
        success=True,
        message="Checked in successfully.",
        data=AttendanceResponse.model_validate(record),
        errors=None,
    )
