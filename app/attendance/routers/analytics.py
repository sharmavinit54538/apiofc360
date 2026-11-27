"""Daily Face Attendance analytics router."""

from __future__ import annotations

from datetime import date
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.core.rbac import require_tenant_admin_or_manager as require_admin_or_manager
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


def _resolve_filter_params(
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    startDate: date | None = Query(None, description="Start date alias (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    endDate: date | None = Query(None, description="End date alias (YYYY-MM-DD)"),
    view_mode: str | None = Query(None, pattern="^(week|month)$", description="View mode: week or month"),
    viewMode: str | None = Query(None, pattern="^(week|month)$", description="View mode alias: week or month"),
    department_id: str | None = Query(None),
    departmentId: str | None = Query(None),
    shift_id: str | None = Query(None),
    shiftId: str | None = Query(None),
    location_id: str | None = Query(None),
    locationId: str | None = Query(None),
) -> dict:
    return {
        "start_date": start_date or startDate,
        "end_date": end_date or endDate,
        "view_mode": view_mode or viewMode or "week",
        "department_id": department_id or departmentId,
        "shift_id": shift_id or shiftId,
        "location_id": location_id or locationId,
    }


@router.get(
    "/analytics/rate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get attendance rate analytics (Admin and Managers)",
)
@router.get(
    "/analytics/rate-kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get attendance rate KPI analytics with period comparison (Admin and Managers)",
)
async def get_attendance_rate(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
    filters: Annotated[dict, Depends(_resolve_filter_params)] = None,
) -> APIResponse[dict]:
    """Get attendance rate analytics for a date range."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_rate(company_id=company_id, **(filters or {}))
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
    filters: Annotated[dict, Depends(_resolve_filter_params)] = None,
) -> APIResponse[dict]:
    """Get attendance distribution (on time, late, absent, on leave) for a date range."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_distribution(company_id=company_id, **(filters or {}))
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
    filters: Annotated[dict, Depends(_resolve_filter_params)] = None,
) -> APIResponse[dict]:
    """Get weekly aggregated attendance data by weekday (Mon-Sun)."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_weekly(company_id=company_id, **(filters or {}))
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
    filters: Annotated[dict, Depends(_resolve_filter_params)] = None,
) -> APIResponse[dict]:
    """Get daily attendance trends for a date range."""
    company_id = _get_company_id(claims)
    service = AttendanceAnalyticsService(db)
    data = await service.get_attendance_trends(company_id=company_id, **(filters or {}))
    return APIResponse[dict](
        success=True,
        message="Attendance trends analytics retrieved.",
        data=data,
        errors=None,
    )