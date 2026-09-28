"""Employee Health router for OFC360 / Aurix HRMS Core Modules (Sensitive Medical Data)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager, _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.core_modules.attendance_service import AttendanceCoreService
from app.services.core_modules.compliance_health_service import EmployeeHealthService
from app.services.employee_health_service import EmployeeHealthService as AIEmployeeHealthService

router = APIRouter(prefix="/employee-health", tags=["Core - Employee Health"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("")
@router.get("/")
async def get_health_overview(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = EmployeeHealthService(session)
    res = await srv.get_analytics(cid)
    return _ok(res)


@router.get("/profile")
async def get_my_health_profile(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    att_srv = AttendanceCoreService(session)
    emp = await att_srv.get_employee_by_user_id(uid)
    emp_id = emp.id if emp else uid
    srv = EmployeeHealthService(session)
    profile = await srv.get_profile(emp_id)
    return _ok(profile)


@router.get("/records")
async def list_health_records(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    uid = _uid(claims)
    att_srv = AttendanceCoreService(session)
    emp = await att_srv.get_employee_by_user_id(uid)
    emp_id = emp.id if emp else uid
    srv = EmployeeHealthService(session)
    res = await srv.list_records(employee_id=emp_id, page=page, limit=limit)
    return _ok(res)


@router.get("/analytics")
async def get_health_analytics(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = EmployeeHealthService(session)
    res = await srv.get_analytics(cid)
    return _ok(res)


# =============================================================================
# Granular AI Employee Health Endpoints (Dashboard, KPI, Burnout Trend, Overtime)
# =============================================================================

@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Employee Health Dashboard",
)
@router.post(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_employee_health_dashboard(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[dict]:
    """Retrieve employee health sentiment, wellbeing score, and burnout dashboard."""
    cid = _get_cid(claims)
    service = AIEmployeeHealthService(session=session)
    dash = await service.get_dashboard(company_id=cid, department_id=department_id)
    dump = dash.model_dump() if hasattr(dash, "model_dump") else dict(dash)
    return APIResponse[dict](
        success=True,
        message="Employee health dashboard fetched successfully.",
        data=dump,
        errors=None,
    )


@router.get(
    "/kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Employee Health KPIs",
)
@router.post(
    "/kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_employee_health_kpis(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[dict]:
    """Slice and retrieve employee health KPI cards."""
    cid = _get_cid(claims)
    service = AIEmployeeHealthService(session=session)
    dash = await service.get_dashboard(company_id=cid, department_id=department_id)
    data = {
        "wellbeing_score": dash.wellbeing_score,
        "wellbeingScore": dash.wellbeingScore,
        "burnout_risk": dash.burnout_risk,
        "burnoutRisk": dash.burnoutRisk,
        "avg_workload": dash.avg_workload,
        "avgWorkload": dash.avgWorkload,
        "ot_hours": dash.ot_hours,
        "otHours": dash.otHours,
        "high_risk_employees": dash.high_risk_employees,
        "highRiskEmployees": dash.high_risk_employees,
        "healthy_employee_pct": dash.healthy_employee_pct,
        "healthyEmployeePct": dash.healthy_employee_pct,
        "wellness_trend": dash.wellness_trend,
        "wellnessTrend": dash.wellness_trend,
        "kpis": [
            {"key": "wellbeing_score", "label": "Wellbeing Score", "value": dash.wellbeing_score, "unit": "/100"},
            {"key": "burnout_risk", "label": "Burnout Risk Index", "value": dash.burnout_risk, "unit": "%"},
            {"key": "avg_workload", "label": "Average Workload", "value": dash.avg_workload, "unit": ""},
            {"key": "ot_hours", "label": "Overtime Hours", "value": dash.ot_hours, "unit": "hrs"},
            {"key": "healthy_employee_pct", "label": "Healthy Workforce", "value": dash.healthy_employee_pct, "unit": "%"},
        ],
    }
    return APIResponse[dict](
        success=True,
        message="Employee health KPIs fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/burnout-trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Employee Burnout Trend",
)
@router.post(
    "/burnout-trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_employee_burnout_trend(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve weekly and monthly burnout trend analytics."""
    cid = _get_cid(claims)
    service = AIEmployeeHealthService(session=session)
    trend = await service.get_burnout_trend(company_id=cid)
    data = {
        "period": trend.period,
        "burnout_trend": trend.burnout_trend,
        "burnoutTrend": trend.burnout_trend,
        "trend": trend.burnout_trend,
    }
    return APIResponse[dict](
        success=True,
        message="Employee burnout trend fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/overtime",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Employee Health Overtime Metrics",
)
@router.post(
    "/overtime",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_employee_overtime(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve overtime tracking and department overtime distribution."""
    cid = _get_cid(claims)
    service = AIEmployeeHealthService(session=session)
    ot = await service.get_overtime(company_id=cid)
    data = {
        "total_ot_hours": ot.total_ot_hours,
        "totalOtHours": ot.total_ot_hours,
        "daily_ot_avg": ot.daily_ot_avg,
        "dailyOtAvg": ot.daily_ot_avg,
        "weekly_ot_avg": ot.weekly_ot_avg,
        "weeklyOtAvg": ot.weekly_ot_avg,
        "monthly_ot_total": ot.monthly_ot_total,
        "monthlyOtTotal": ot.monthly_ot_total,
        "team_overtime": ot.team_overtime,
        "teamOvertime": ot.team_overtime,
        "top_ot_employees": ot.top_ot_employees,
        "topOtEmployees": ot.top_ot_employees,
        "budget_impact": ot.budget_impact,
        "budgetImpact": ot.budget_impact,
    }
    return APIResponse[dict](
        success=True,
        message="Employee health overtime fetched successfully.",
        data=data,
        errors=None,
    )

