"""Daily Face Attendance break tracking routes (/api/v1/attendance/break/*)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.face import BreakEndRequest, BreakSessionResponse, BreakStartRequest
from app.attendance.services.break_service import BreakService
from app.attendance.utils.helpers import parse_face_request
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/break", tags=["Face Attendance Breaks"])


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> uuid.UUID:
    cid = claims.get("company_id")
    if not cid:
        raise AppException("Company context missing in user authentication claims.", status_code=403)
    return uuid.UUID(str(cid))


@router.post(
    "/start",
    status_code=status.HTTP_200_OK,
    summary="Start an attendance break session with real face verification",
)
async def start_break(
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Starts a new break session for today's active check-in with mandatory face verification."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    ip_address = request.client.host if request and request.client else None

    image_b64, location_dict, notes, device_info = await parse_face_request(
        request,
        require_image=True,
        missing_image_message="Face image is required for break verification.",
    )

    service = BreakService(db)
    break_session = await service.start_break(
        user_id=user_id,
        company_id=company_id,
        image_base64=image_b64,
        location=location_dict,
        notes=notes,
        device_info=device_info,
        ip_address=ip_address,
    )

    return {
        "success": True,
        "message": "Break session started successfully.",
        "data": {
            "id": str(break_session.id),
            "attendance_id": str(break_session.attendance_id),
            "break_start": break_session.break_start.isoformat(),
            "status": break_session.status,
            "notes": break_session.notes,
            "face_distance": break_session.start_face_distance,
            "liveness_score": break_session.start_liveness_score,
            "image_url": break_session.start_image_url,
            "start_image_url": break_session.start_image_url,
        },
        "error": None,
    }


@router.post(
    "/end",
    status_code=status.HTTP_200_OK,
    summary="End the currently active attendance break session with real face verification",
)
async def end_break(
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Ends the currently active break session with mandatory face verification and records duration."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    ip_address = request.client.host if request and request.client else None

    image_b64, location_dict, notes, device_info = await parse_face_request(
        request,
        require_image=True,
        missing_image_message="Face image is required for break verification.",
    )

    service = BreakService(db)
    break_session = await service.end_break(
        user_id=user_id,
        company_id=company_id,
        image_base64=image_b64,
        location=location_dict,
        notes=notes,
        device_info=device_info,
        ip_address=ip_address,
    )

    return {
        "success": True,
        "message": "Break session ended successfully.",
        "data": {
            "id": str(break_session.id),
            "attendance_id": str(break_session.attendance_id),
            "break_start": break_session.break_start.isoformat(),
            "break_end": break_session.break_end.isoformat() if break_session.break_end else None,
            "duration_minutes": break_session.duration_minutes,
            "status": break_session.status,
            "notes": break_session.notes,
            "face_distance": break_session.end_face_distance,
            "liveness_score": break_session.end_liveness_score,
            "image_url": break_session.end_image_url,
            "end_image_url": break_session.end_image_url,
        },
        "error": None,
    }
