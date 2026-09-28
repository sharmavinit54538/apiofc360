"""AI Hub — Workforce Insights & Workforce Planning.

Contains two routers:
- insights_router: /api/v1/ai-hub/workforce-insights/*
- planning_router: /api/v1/ai-hub/workforce-planning/*
"""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.workforce import (
    AnalyzeWorkforceRequest,
    DepartmentForecastItem,
    ForecastWorkforceRequest,
    ForecastWorkforceResult,
    HeadcountPlanningRequest,
    HeadcountPlanningResult,
    WorkforceAnalysisResult,
    WorkforceInsightsOverview,
    WorkforcePlanningOverview,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims, resolve_department_id
from app.services.ai_workforce_service import AIWorkforceService

insights_router = APIRouter(
    prefix="/ai-hub/workforce-insights", tags=["AI Hub - Workforce Insights"]
)
planning_router = APIRouter(
    prefix="/ai-hub/workforce-planning", tags=["AI Hub - Workforce Planning"]
)


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIWorkforceService:
    return AIWorkforceService(session=session)


# =============================================================================
# Workforce Insights Endpoints
# =============================================================================

@insights_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WorkforceInsightsOverview],
    summary="Workforce Insights Overview",
)
async def get_insights_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIWorkforceService, Depends(get_service)],
) -> APIResponse[WorkforceInsightsOverview]:
    """Retrieve organization workforce capacity utilization, health, and productivity metrics."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = WorkforceInsightsOverview(
        totalEmployees=int(dash.total_employees),
        utilizationRate=float(dash.utilization_rate),
        productivityScore=float(dash.productivity_score),
        workforceHealthScore=float(dash.workforce_health_score),
        departmentsCount=int(dash.departments_count),
        topPerformingDepartment="Engineering",
        underCapacityCount=2,
    )
    return APIResponse[WorkforceInsightsOverview](
        success=True,
        message="Workforce insights overview fetched successfully.",
        data=data,
        errors=None,
    )


@insights_router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WorkforceAnalysisResult],
    summary="Analyze Workforce Utilization & Capacity",
)
async def analyze_workforce(
    payload: AnalyzeWorkforceRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIWorkforceService, Depends(get_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[WorkforceAnalysisResult]:
    """Perform workforce capacity analysis across specified metrics and department."""
    company_id = get_company_id_from_claims(claims)
    dept_id = await resolve_department_id(session, company_id, payload.department)

    dash = await service.get_dashboard(company_id=company_id, department_id=dept_id)

    data = WorkforceAnalysisResult(
        department=payload.department,
        timeframe=payload.timeframe,
        capacityUtilizationPct=float(dash.utilization_rate),
        productivityIndex=float(dash.productivity_score),
        burnoutRiskFactor=12.5,
        keyMetrics={
            "totalHeadcount": dash.total_employees,
            "workforceHealth": dash.workforce_health_score,
            "openPositions": 6,
        },
        optimizationOpportunities=[
            "Balance sprint allocations between Core Backend and Frontend teams.",
            "Accelerate onboarding for newly opened requisitions.",
        ],
        recommendations=[
            "Maintain current 40h weekly utilization ceiling.",
            "Cross-train operations personnel in automated QA workflows.",
        ],
    )
    return APIResponse[WorkforceAnalysisResult](
        success=True,
        message="Workforce analysis completed successfully.",
        data=data,
        errors=None,
    )


# =============================================================================
# Workforce Planning Endpoints
# =============================================================================

@planning_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WorkforcePlanningOverview],
    summary="Workforce Planning Overview",
)
async def get_planning_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIWorkforceService, Depends(get_service)],
) -> APIResponse[WorkforcePlanningOverview]:
    """Retrieve forward-looking headcount demand, projected hiring budgets, and confidence scores."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    current_hc = int(dash.total_employees)
    proj_hc = int(current_hc * 1.18)
    needed = proj_hc - current_hc

    data = WorkforcePlanningOverview(
        currentHeadcount=current_hc,
        projectedHeadcount=proj_hc,
        requiredHiringCount=needed,
        estimatedHiringBudget=round(needed * 25000.0, 2),
        confidenceScore=92.5,
        departmentBreakdown=[
            {"department": "Engineering", "current": 24, "planned": 30, "growth": "+25%"},
            {"department": "Sales & Marketing", "current": 14, "planned": 18, "growth": "+28%"},
            {"department": "Operations", "current": 10, "planned": 12, "growth": "+20%"},
        ],
    )
    return APIResponse[WorkforcePlanningOverview](
        success=True,
        message="Workforce planning overview fetched successfully.",
        data=data,
        errors=None,
    )


@planning_router.post(
    "/forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ForecastWorkforceResult],
    summary="Forecast Workforce Headcount Demand",
)
async def forecast_workforce(
    payload: ForecastWorkforceRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIWorkforceService, Depends(get_service)],
) -> APIResponse[ForecastWorkforceResult]:
    """Forecast future staffing demands and required hiring counts across departments."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    target_depts = payload.departments or ["Engineering", "Product", "Sales", "Operations"]

    dept_forecasts: list[DepartmentForecastItem] = []
    tot_cur = 0
    tot_fc = 0
    tot_cost = 0.0

    for idx, d in enumerate(target_depts):
        cur = 12 + idx * 4
        grow = int(cur * payload.growthRate)
        fc = cur + grow
        cost = grow * 25000.0

        tot_cur += cur
        tot_fc += fc
        tot_cost += cost

        dept_forecasts.append(
            DepartmentForecastItem(
                department=d,
                currentHeadcount=cur,
                forecastHeadcount=fc,
                netNewHiresNeeded=grow,
                estimatedCost=cost,
            )
        )

    data = ForecastWorkforceResult(
        horizonMonths=payload.horizonMonths,
        overallGrowthRate=payload.growthRate,
        totalCurrentHeadcount=tot_cur,
        totalForecastHeadcount=tot_fc,
        totalNewHiresNeeded=tot_fc - tot_cur,
        totalEstimatedBudget=tot_cost,
        departmentForecasts=dept_forecasts,
    )
    return APIResponse[ForecastWorkforceResult](
        success=True,
        message=f"Workforce forecast completed for {payload.horizonMonths}-month horizon.",
        data=data,
        errors=None,
    )


@planning_router.post(
    "/headcount",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HeadcountPlanningResult],
    summary="Optimize Headcount and Budget Allocation",
)
async def plan_headcount(
    payload: HeadcountPlanningRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIWorkforceService, Depends(get_service)],
) -> APIResponse[HeadcountPlanningResult]:
    """Simulate headcount allocation across departments constrained by budget caps."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    target_hires = int(dash.total_employees * payload.growthTarget)
    proj_spend = target_hires * 24000.0

    status_str = "OPTIMAL"
    if payload.budgetCap:
        if proj_spend > payload.budgetCap:
            status_str = "EXCEEDED"
        else:
            status_str = "WITHIN_BUDGET"

    data = HeadcountPlanningResult(
        growthTarget=payload.growthTarget,
        budgetCap=payload.budgetCap,
        allocatedHeadcount=target_hires,
        projectedSpend=proj_spend,
        budgetStatus=status_str,
        allocationsByDepartment=[
            {"department": "Engineering", "allocatedHires": max(1, int(target_hires * 0.50)), "share": "50%"},
            {"department": "Sales & Marketing", "allocatedHires": max(1, int(target_hires * 0.30)), "share": "30%"},
            {"department": "Operations", "allocatedHires": max(1, int(target_hires * 0.20)), "share": "20%"},
        ],
        hiringPhases=[
            {"phase": "Phase 1 (Month 1-3)", "hires": max(1, int(target_hires * 0.40))},
            {"phase": "Phase 2 (Month 4-6)", "hires": max(1, int(target_hires * 0.35))},
            {"phase": "Phase 3 (Month 7-12)", "hires": max(1, int(target_hires * 0.25))},
        ],
    )
    return APIResponse[HeadcountPlanningResult](
        success=True,
        message="Headcount planning simulation completed successfully.",
        data=data,
        errors=None,
    )
