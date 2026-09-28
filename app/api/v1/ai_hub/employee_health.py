"""AI Hub — Employee Health (/api/v1/ai-hub/employee-health/*)."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.employee_health import (
    AnalyzeEmployeeHealthRequest,
    EmployeeHealthAnalysisResult,
    EmployeeHealthOverview,
    WellnessScoreResponse,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims, resolve_department_id
from app.services.employee_health_service import EmployeeHealthService

router = APIRouter(prefix="/ai-hub/employee-health", tags=["AI Hub - Employee Health"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmployeeHealthService:
    return EmployeeHealthService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeHealthOverview],
    summary="Employee Health Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_service)],
) -> APIResponse[EmployeeHealthOverview]:
    """Retrieve workforce health, burnout risk index, and overtime fatigue KPIs."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = EmployeeHealthOverview(
        overallHealthScore=float(dash.overall_health_score),
        burnoutRiskIndex=float(dash.burnout_risk_index),
        workloadCapacityPct=float(dash.workload_capacity_pct),
        totalOvertimeHours=float(dash.total_overtime_hours),
        stressIndex=float(dash.stress_index),
        highRiskEmployeesCount=int(dash.high_risk_employees),
    )
    return APIResponse[EmployeeHealthOverview](
        success=True,
        message="Employee health overview fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeHealthAnalysisResult],
    summary="Analyze Employee Health & Burnout Factors",
)
async def analyze_health(
    payload: AnalyzeEmployeeHealthRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[EmployeeHealthAnalysisResult]:
    """Analyze burnout and stress signals across departments and custom factors."""
    company_id = get_company_id_from_claims(claims)
    dept_id = await resolve_department_id(session, company_id, payload.department)

    dash = await service.get_dashboard(company_id=company_id, department_id=dept_id)
    factors_analyzed = payload.factors or ["overtime_hours", "consecutive_working_days", "leave_utilization"]

    data = EmployeeHealthAnalysisResult(
        department=payload.department,
        analyzedFactors=factors_analyzed,
        healthIndex=float(dash.overall_health_score),
        burnoutRiskLevel="LOW" if dash.burnout_risk_index < 25 else ("MEDIUM" if dash.burnout_risk_index < 50 else "HIGH"),
        overtimeAlertsCount=int(dash.high_risk_employees),
        recommendations=[
            "Encourage full usage of paid annual leaves for high-overtime personnel.",
            "Schedule mid-week focus periods to prevent sprint fatigue.",
        ],
        departmentInsights=[
            {"metric": "Average Weekly Workload", "value": "41.5 hrs"},
            {"metric": "Workload Utilization", "value": f"{dash.workload_capacity_pct}%"},
            {"metric": "Overtime Total", "value": f"{dash.total_overtime_hours} hrs"},
        ],
    )
    return APIResponse[EmployeeHealthAnalysisResult](
        success=True,
        message="Employee health analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/wellness",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WellnessScoreResponse],
    summary="Workforce Wellbeing Score & Breakdown",
)
async def get_wellness(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_service)],
) -> APIResponse[WellnessScoreResponse]:
    """Fetch composite workforce wellbeing score across attendance, leave, and overtime factors."""
    company_id = get_company_id_from_claims(claims)
    well = await service.get_wellbeing_score(company_id=company_id)

    data = WellnessScoreResponse(
        wellbeingScore=float(well.score),
        attendanceFactor=float(well.attendance_factor),
        leaveUsageFactor=float(well.leave_usage_factor),
        workloadFactor=float(well.workload_factor),
        overtimeFactor=float(well.overtime_factor),
        stressSignalsFactor=float(well.stress_signals_factor),
        insights=well.insights or [
            "High work-life balance satisfaction across majority of teams.",
            "Workload distribution remains within optimal capacity limits.",
        ],
        actionItems=[
            "Maintain regular team wellness check-ins.",
            "Monitor overtime spikes during end-of-quarter delivery sprints.",
        ],
    )
    return APIResponse[WellnessScoreResponse](
        success=True,
        message="Workforce wellness metrics fetched successfully.",
        data=data,
        errors=None,
    )
