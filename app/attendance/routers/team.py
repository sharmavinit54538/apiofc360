"""Daily Face Attendance manager team view router."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.response import AttendanceResponse
from app.attendance.services.history_service import AttendanceHistoryService
from app.core.exceptions import AppException
from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session

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
    return uuid.UUID(str(company_id_str))


@router.get(
    "/face/team",
    status_code=status.HTTP_200_OK,
    summary="Retrieve direct report employees' daily attendance logs history",
)
async def get_team_attendance_history(
    start_date: Optional[date] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date filter (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Records limit per page"),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> dict:
    """Retrieve historical daily check-in logs for direct reporting employees."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)

    service = AttendanceHistoryService(db)
    items, total = await service.get_team_attendance(
        user_id,
        company_id=company_id,
        page=page,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
    )

    serialized = [AttendanceResponse.model_validate(item).model_dump(mode="json") for item in items]
    data = {
        "page": page,
        "limit": limit,
        "total": total,
        "items": serialized,
    }
    return {
        "success": True,
        "message": "Direct reports attendance history logs retrieved.",
        "data": data,
        "error": None,
    }
