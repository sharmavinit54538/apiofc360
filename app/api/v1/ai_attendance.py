"""FastAPI router for AI Attendance Monitor endpoints (/api/v1/ai/attendance/*)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai_attendance import (
    AbsencePatternResponse,
    AnomaliesResponse,
    AttendanceDashboardResponse,
    AttendanceHealthScoreResponse,
    AttendanceTrendResponse,
    LateArrivalsResponse,
    OvertimeResponse,
    ShiftViolationsResponse,
    WatchlistResponse,
)
from app.services.ai_attendance_service import AIAttendanceService

router = APIRouter(prefix="/ai/attendance", tags=["AI Attendance Monitor"])


async def get_ai_attendance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIAttendanceService:
    return AIAttendanceService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceDashboardResponse],
    summary="Get AI Attendance Dashboard KPIs",
)
async def get_attendance_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
) -> APIResponse[AttendanceDashboardResponse]:
    """Retrieve dynamic attendance KPIs: Health Score, Attendance %, Anomalies, Late Arrivals, Overtime Hours, Today Present, Today Absent."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(
        company_id=company_id,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse[AttendanceDashboardResponse](
        success=True,
        message="Attendance dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceTrendResponse],
    summary="Get Attendance Trend Chart Data",
)
async def get_attendance_trend(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    group_by: str = Query("daily", description="daily | weekly | monthly | department | shift"),
    department_id: Optional[uuid.UUID] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
) -> APIResponse[AttendanceTrendResponse]:
    """Retrieve attendance percentage trend grouped by daily, weekly, monthly, department, or shift."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_trend(
        company_id=company_id,
        group_by=group_by,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse[AttendanceTrendResponse](
        success=True,
        message="Attendance trend fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/late-arrivals",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LateArrivalsResponse],
    summary="Get Late Arrival Detection Data",
)
async def get_late_arrivals(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
) -> APIResponse[LateArrivalsResponse]:
    """Retrieve late arrival records, expected vs actual check-in times, delay minutes, and employee frequencies."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_late_arrivals(
        company_id=company_id,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse[LateArrivalsResponse](
        success=True,
        message="Late arrivals data fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/anomalies",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnomaliesResponse],
    summary="Get Attendance Anomaly Detection Results",
)
async def get_anomalies(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[AnomaliesResponse]:
    """Detect attendance anomalies (Missing Check-In/Out, Geofence violations, Shift breaches)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_anomalies(company_id=company_id, department_id=department_id)
    return APIResponse[AnomaliesResponse](
        success=True,
        message="Attendance anomalies fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/absence-pattern",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AbsencePatternResponse],
    summary="Get AI Absence Pattern Insights",
)
async def get_absence_patterns(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[AbsencePatternResponse]:
    """Detect absence patterns: Friday/Monday leave clusters, long weekend gaps, and repeated leave trends."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_absence_patterns(company_id=company_id, department_id=department_id)
    return APIResponse[AbsencePatternResponse](
        success=True,
        message="Absence patterns fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/overtime",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[OvertimeResponse],
    summary="Get Overtime Tracking Metrics",
)
async def get_overtime(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[OvertimeResponse]:
    """Retrieve daily, weekly, and monthly overtime totals, department breakdowns, and estimated budget impact."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_overtime(company_id=company_id, department_id=department_id)
    return APIResponse[OvertimeResponse](
        success=True,
        message="Overtime metrics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/shift-violations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ShiftViolationsResponse],
    summary="Get Shift Violation Detection Data",
)
async def get_shift_violations(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[ShiftViolationsResponse]:
    """Detect shift violations: Missed Shift, Early Logout, Late Login, No Punch, Policy Breaches."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_shift_violations(company_id=company_id, department_id=department_id)
    return APIResponse[ShiftViolationsResponse](
        success=True,
        message="Shift violations fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/health-score",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceHealthScoreResponse],
    summary="Get Composite Attendance Health Score",
)
async def get_health_score(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[AttendanceHealthScoreResponse]:
    """Calculate composite Attendance Health Score (0-100) using attendance %, late %, leave %, OT %, and shift compliance."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_health_score(company_id=company_id, department_id=department_id)
    return APIResponse[AttendanceHealthScoreResponse](
        success=True,
        message="Attendance health score fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/watchlist",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WatchlistResponse],
    summary="Get Absentee Watchlist",
)
async def get_watchlist(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_ai_attendance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[WatchlistResponse]:
    """Retrieve employees at risk of chronic absenteeism with risk levels and AI HR recommendations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_watchlist(company_id=company_id, department_id=department_id)
    return APIResponse[WatchlistResponse](
        success=True,
        message="Absentee watchlist fetched successfully.",
        data=data,
        errors=None,
    )
