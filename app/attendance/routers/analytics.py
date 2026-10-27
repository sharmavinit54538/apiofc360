"""Daily Face Attendance analytics router."""

from __future__ import annotations

from datetime import date
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status
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


@router.get(
    "/analytics/rate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get attendance rate analytics (Admin and Managers)",
)
async def get_attendance_rate(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    view_mode: str = Query("week", pattern="^(week|month)$", description="View mode: week or month"),
) -> APIResponse[dict]:
    """Get attendance rate analytics for a date range."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_rate(
        company_id=company_id, start_date=start_date, end_date=end_date, view_mode=view_mode
    )
    return APIResponse[dict](
        success=True,
        message="Attendance rate analytics retrieved.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics/distribution",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get attendance distribution analytics (Admin and Managers)",
)
async def get_attendance_distribution(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    view_mode: str = Query("week", pattern="^(week|month)$", description="View mode: week or month"),
) -> APIResponse[dict]:
    """Get attendance distribution (on time, late, absent) for a date range."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_distribution(
        company_id=company_id, start_date=start_date, end_date=end_date, view_mode=view_mode
    )
    return APIResponse[dict](
        success=True,
        message="Attendance distribution analytics retrieved.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics/weekly",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get weekly attendance analytics by weekday (Admin and Managers)",
)
async def get_attendance_weekly(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    view_mode: str = Query("week", pattern="^(week|month)$", description="View mode: week or month"),
) -> APIResponse[dict]:
    """Get weekly aggregated attendance data by weekday (Mon-Sun)."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_weekly(
        company_id=company_id, start_date=start_date, end_date=end_date, view_mode=view_mode
    )
    return APIResponse[dict](
        success=True,
        message="Weekly attendance analytics retrieved.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics/trends",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get attendance trends analytics (Admin and Managers)",
)
async def get_attendance_trends(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    view_mode: str = Query("week", pattern="^(week|month)$", description="View mode: week or month"),
) -> APIResponse[dict]:
    """Get daily attendance trends for a date range."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_trends(
        company_id=company_id, start_date=start_date, end_date=end_date, view_mode=view_mode
    )
    return APIResponse[dict](
        success=True,
        message="Attendance trends analytics retrieved.",
        data=data,
        errors=None,
    )