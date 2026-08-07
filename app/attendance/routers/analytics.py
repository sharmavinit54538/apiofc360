"""Daily Face Attendance analytics router."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.core.rbac import require_admin_or_manager
from app.schemas.auth import APIResponse
from app.attendance.services.analytics_service import AttendanceAnalyticsService

router = APIRouter()


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise AppException(
            message="Company context missing in user authentication claims.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return uuid.UUID(company_id_str)


@router.get(
    "/face/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Retrieve attendance dashboard analytics summary (Admin and Managers)",
)
async def get_attendance_analytics(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve today's overview stats, presence rates, and active headcounts."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    stats = await service.get_company_analytics(company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="Attendance analytics retrieved.",
        data=stats,
        errors=None,
    )
