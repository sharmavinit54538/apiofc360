"""Daily Face Attendance break tracking routes (/api/v1/attendance/break/*)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.face import BreakSessionResponse, BreakStartRequest
from app.attendance.services.break_service import BreakService
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
    summary="Start an attendance break session",
)
async def start_break(
    payload: Optional[BreakStartRequest] = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    request: Request = None,
) -> dict:
    """Starts a new break session for today's active check-in."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    ip_address = request.client.host if request and request.client else None

    service = BreakService(db)
    notes = payload.notes if payload else None
    break_session = await service.start_break(
        user_id=user_id, company_id=company_id, notes=notes, ip_address=ip_address
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
        },
        "error": None,
    }


@router.post(
    "/end",
    status_code=status.HTTP_200_OK,
    summary="End the currently active attendance break session",
)
async def end_break(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    request: Request = None,
) -> dict:
    """Ends the currently active break session and records duration."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    ip_address = request.client.host if request and request.client else None

    service = BreakService(db)
    break_session = await service.end_break(
        user_id=user_id, company_id=company_id, ip_address=ip_address
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
        },
        "error": None,
    }
