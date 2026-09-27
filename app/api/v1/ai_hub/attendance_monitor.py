"""AI Hub — Attendance Monitor (/api/v1/ai-hub/attendance-monitor/*)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.attendance_monitor import (
    AnalyzeAttendanceRequest,
    AttendanceAnomaliesPage,
    AttendanceAnomalyItem,
    AttendanceAnalysisResult,
    AttendanceMonitorOverview,
)
from app.schemas.auth import APIResponse
from app.services.ai_attendance_service import AIAttendanceService
from app.services.ai_hub.utils import get_company_id_from_claims, resolve_department_id

router = APIRouter(prefix="/ai-hub/attendance-monitor", tags=["AI Hub - Attendance Monitor"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIAttendanceService:
    return AIAttendanceService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceMonitorOverview],
    summary="Attendance Monitor Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_service)],
) -> APIResponse[AttendanceMonitorOverview]:
    """Fetch attendance monitoring KPIs and health overview."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = AttendanceMonitorOverview(
        attendanceHealthScore=float(dash.attendance_health_score),
        totalAttendancePercentage=float(dash.total_attendance_percentage),
        totalAnomalies=int(dash.total_anomalies),
        lateArrivals=int(dash.late_arrivals),
        overtimeHours=float(dash.overtime_hours),
        todayPresentEmployees=int(dash.today_present_employees),
        todayAbsentEmployees=int(dash.today_absent_employees),
    )
    return APIResponse[AttendanceMonitorOverview](
        success=True,
        message="Attendance monitor overview fetched.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceAnalysisResult],
    summary="Analyze Attendance Range and Trends",
)
async def analyze_attendance(
    payload: AnalyzeAttendanceRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AttendanceAnalysisResult]:
    """Execute date-range attendance analysis filtered optionally by department."""
    company_id = get_company_id_from_claims(claims)
    dept_id = await resolve_department_id(session, company_id, payload.department)

    start_d: Optional[date] = None
    end_d: Optional[date] = None
    try:
        start_d = date.fromisoformat(payload.startDate)
    except (ValueError, TypeError):
        pass
    try:
        end_d = date.fromisoformat(payload.endDate)
    except (ValueError, TypeError):
        pass

    dash = await service.get_dashboard(
        company_id=company_id,
        department_id=dept_id,
        start_date=start_d,
        end_date=end_d,
    )

    data = AttendanceAnalysisResult(
        period=f"{payload.startDate} to {payload.endDate}",
        department=payload.department,
        attendanceRate=float(dash.total_attendance_percentage),
        anomaliesCount=int(dash.total_anomalies),
        lateArrivalsCount=int(dash.late_arrivals),
        overtimeHours=float(dash.overtime_hours),
        summary=(
            f"Attendance rate averaged {dash.total_attendance_percentage}% across period with "
            f"{dash.total_anomalies} anomalies and {dash.late_arrivals} late arrivals."
        ),
        insights=[
            "Attendance compliance remained steady across target timeframe.",
            "Review shift start allocations to reduce morning arrival bottlenecks.",
        ],
    )
    return APIResponse[AttendanceAnalysisResult](
        success=True,
        message="Attendance analysis completed.",
        data=data,
        errors=None,
    )


@router.get(
    "/anomalies",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceAnomaliesPage],
    summary="List Attendance Anomalies (Paginated)",
)
async def list_anomalies(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIAttendanceService, Depends(get_service)],
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, alias="sortBy"),
    sort_order: Optional[str] = Query(None, alias="sortOrder"),
) -> APIResponse[AttendanceAnomaliesPage]:
    """Retrieve paginated list of attendance anomalies with optional search and sorting."""
    company_id = get_company_id_from_claims(claims)
    res = await service.get_anomalies(company_id=company_id)

    raw_items = res.items

    # Convert to DTO items
    items: list[AttendanceAnomalyItem] = [
        AttendanceAnomalyItem(
            id=str(item.id),
            employeeId=str(item.employee_id),
            employeeName=item.employee_name,
            department=item.department,
            date=item.date,
            anomalyType=item.anomaly_type,
            severity=item.severity,
            description=item.description,
        )
        for item in raw_items
    ]

    # Search filter
    if search:
        s_lower = search.lower()
        items = [
            it for it in items
            if s_lower in it.employeeName.lower()
            or s_lower in it.department.lower()
            or s_lower in it.anomalyType.lower()
            or s_lower in it.description.lower()
        ]

    # Sort
    if sort_by and hasattr(AttendanceAnomalyItem, sort_by):
        reverse = (sort_order or "").lower() == "desc"
        items.sort(key=lambda x: getattr(x, sort_by), reverse=reverse)

    total = len(items)
    offset = (page - 1) * limit
    paged_items = items[offset : offset + limit]
    pages = (total + limit - 1) // limit if limit > 0 else 0

    data = AttendanceAnomaliesPage(
        items=paged_items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
    return APIResponse[AttendanceAnomaliesPage](
        success=True,
        message="Attendance anomalies fetched.",
        data=data,
        errors=None,
    )
