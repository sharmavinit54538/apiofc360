"""Daily Face Attendance personal history router."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.attendance.schemas.response import AttendanceResponse
from app.attendance.schemas.history import AttendanceHistoryResponse
from app.attendance.services.history_service import AttendanceHistoryService

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


@router.get(
    "/face/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceHistoryResponse],
    summary="Retrieve personal paginated daily attendance logs history",
)
async def get_own_attendance_history(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Records limit per page"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[AttendanceHistoryResponse]:
    """Retrieve historical daily check-in log records for current employee."""
    user_id = _get_user_id(claims)
    service = AttendanceHistoryService(db)
    items, total = await service.get_own_history(user_id, page=page, limit=limit)
    
    serialized = [AttendanceResponse.model_validate(item) for item in items]
    data = AttendanceHistoryResponse(page=page, limit=limit, total=total, items=serialized)
    return APIResponse[AttendanceHistoryResponse](
        success=True,
        message="Attendance history logs retrieved.",
        data=data,
        errors=None,
    )
