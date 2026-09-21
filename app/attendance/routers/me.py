"""Daily Face Attendance current employee status router."""

from __future__ import annotations

import logging
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.attendance.schemas.response import AttendanceTodayResponse
from app.attendance.services.history_service import AttendanceHistoryService

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


@router.get(
    "/face/me",
    status_code=status.HTTP_200_OK,
    summary="Get today's real attendance, shift, break, and biometric status for current employee",
)
async def get_today_punch_state(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Retrieve verified attendance, shift timings, break sessions, and face enrollment state."""
    user_id = _get_user_id(claims)
    service = AttendanceHistoryService(db)
    result = await service.get_today_attendance(user_id)

    # Validate against response schema
    validated = AttendanceTodayResponse(**result)

    return {
        "success": True,
        "message": result.get("message", "Today's punch status retrieved."),
        "data": validated.model_dump(mode="json"),
        "error": None,
    }
