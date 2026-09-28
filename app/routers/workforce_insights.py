"""Workforce Insights router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.ai_workforce_service import AIWorkforceService
from app.services.core_modules.misc_service import WorkforceInsightsService

router = APIRouter(prefix="/workforce-insights", tags=["Core - Workforce Insights"])


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
@router.get("/workforce")
async def get_workforce_summary(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = WorkforceInsightsService(session)
    res = await srv.get_summary(cid)
    return _ok(res)


@router.get("/headcount")
async def get_headcount_insights(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = WorkforceInsightsService(session)
    res = await srv.get_headcount_insights(cid)
    return _ok(res)


@router.get("/trends")
async def get_workforce_trends(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = WorkforceInsightsService(session)
    res = await srv.get_trends(cid)
    return _ok(res)


# =============================================================================
# Granular AI Workforce Insights Endpoints (Dashboard, KPI, Trends, Comparison)
# =============================================================================

@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Workforce Insights Dashboard",
)
@router.post(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_workforce_dashboard(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[dict]:
    """Retrieve workforce planning dashboard KPIs and metrics."""
    company_id = _get_cid(claims)
    service = AIWorkforceService(session=session)
    dash = await service.get_dashboard(company_id=company_id, department_id=department_id)
    dump = dash.model_dump() if hasattr(dash, "model_dump") else dict(dash)
    dump.update({
        "plannedHires": dump.get("planned_hires", 0),
        "openPositions": dump.get("open_positions", 0),
        "capacityUtilizationPct": dump.get("capacity_utilization_pct", 0.0),
        "workforceSize": dump.get("workforce_size", 0),
        "activeEmployees": dump.get("active_employees", 0),
        "totalDepartments": dump.get("total_departments", 0),
        "forecastHorizon": dump.get("forecast_horizon", ""),
        "hiringBudget": dump.get("hiring_budget", 0.0),
        "vacancyRate": dump.get("vacancy_rate", 0.0),
    })
    return APIResponse[dict](
        success=True,
        message="Workforce insights dashboard fetched successfully.",
        data=dump,
        errors=None,
    )


@router.get(
    "/kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Workforce Insights KPIs",
)
@router.post(
    "/kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_workforce_kpis(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[dict]:
    """Slice and retrieve workforce KPI summary cards."""
    company_id = _get_cid(claims)
    service = AIWorkforceService(session=session)
    dash = await service.get_dashboard(company_id=company_id, department_id=department_id)
    data = {
        "planned_hires": dash.planned_hires,
        "open_positions": dash.open_positions,
        "capacity_utilization_pct": dash.capacity_utilization_pct,
        "workforce_size": dash.workforce_size,
        "active_employees": dash.active_employees,
        "total_departments": dash.total_departments,
        "forecast_horizon": dash.forecast_horizon,
        "hiring_budget": dash.hiring_budget,
        "vacancy_rate": dash.vacancy_rate,
        "plannedHires": dash.planned_hires,
        "openPositions": dash.open_positions,
        "capacityUtilizationPct": dash.capacity_utilization_pct,
        "workforceSize": dash.workforce_size,
        "activeEmployees": dash.active_employees,
        "totalDepartments": dash.total_departments,
        "forecastHorizon": dash.forecast_horizon,
        "hiringBudget": dash.hiring_budget,
        "vacancyRate": dash.vacancy_rate,
        "kpis": [
            {"key": "workforce_size", "label": "Workforce Size", "value": dash.workforce_size, "unit": "employees"},
            {"key": "capacity_utilization_pct", "label": "Capacity Utilization", "value": dash.capacity_utilization_pct, "unit": "%"},
            {"key": "open_positions", "label": "Open Positions", "value": dash.open_positions, "unit": "roles"},
            {"key": "planned_hires", "label": "Planned Hires", "value": dash.planned_hires, "unit": "hires"},
            {"key": "vacancy_rate", "label": "Vacancy Rate", "value": dash.vacancy_rate, "unit": "%"},
            {"key": "hiring_budget", "label": "Hiring Budget", "value": dash.hiring_budget, "unit": "$"},
        ],
    }
    return APIResponse[dict](
        success=True,
        message="Workforce insights KPIs fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/headcount-trends",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Workforce Headcount Trends",
)
@router.post(
    "/headcount-trends",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_workforce_headcount_trends(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve historical and projected headcount & workforce trends."""
    company_id = _get_cid(claims)
    service = AIWorkforceService(session=session)
    analytics = await service.get_analytics(company_id=company_id)
    data = {
        "headcount_trends": analytics.headcount_trend,
        "headcountTrends": analytics.headcount_trend,
        "trends": analytics.headcount_trend,
        "hiring_trend": analytics.hiring_trend,
        "hiringTrend": analytics.hiring_trend,
        "attrition_trend": analytics.attrition_trend,
        "attritionTrend": analytics.attrition_trend,
        "productivity_trend": analytics.productivity_trend,
        "productivityTrend": analytics.productivity_trend,
    }
    return APIResponse[dict](
        success=True,
        message="Workforce headcount trends fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/department-comparison",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Workforce Department Comparison",
)
@router.post(
    "/department-comparison",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_workforce_department_comparison(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve department-wise workforce capacity, demand, and utilization comparison."""
    company_id = _get_cid(claims)
    service = AIWorkforceService(session=session)
    cap = await service.get_capacity_demand(company_id=company_id)
    depts = [d.model_dump() if hasattr(d, "model_dump") else d for d in cap.department_capacity]
    data = {
        "total_capacity": cap.total_capacity,
        "totalCapacity": cap.total_capacity,
        "total_demand": cap.total_demand,
        "totalDemand": cap.total_demand,
        "department_comparison": depts,
        "departmentComparison": depts,
        "departments": depts,
    }
    return APIResponse[dict](
        success=True,
        message="Workforce department comparison fetched successfully.",
        data=data,
        errors=None,
    )

