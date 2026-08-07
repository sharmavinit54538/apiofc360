"""Daily Face Attendance current employee status router."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.attendance.schemas.response import AttendanceTodayResponse
from app.attendance.services.history_service import AttendanceHistoryService

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


@router.get(
    "/face/me",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceTodayResponse],
    summary="Get today's daily face attendance punch state for current employee",
)
async def get_today_punch_state(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[AttendanceTodayResponse]:
    """Retrieve check-in and check-out times for the current day."""
    user_id = _get_user_id(claims)
    service = AttendanceHistoryService(db)
    result = await service.get_today_attendance(user_id)
    return APIResponse[AttendanceTodayResponse](
        success=True,
        message="Today's punch status retrieved.",
        data=AttendanceTodayResponse(**result),
        errors=None,
    )
