"""FastAPI router for AI Employee Health endpoints (/api/v1/ai/employee-health/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.employee_health import (
    AnalyzeHealthPayload,
    BurnoutAnalysisPayload,
    BurnoutRiskResponse,
    BurnoutTrendResponse,
    EmployeeHealthAnalyticsResponse,
    EmployeeHealthDashboardResponse,
    EmployeeHealthDetailResponse,
    GenerateInsightsPayload,
    OvertimeResponse,
    StressIndicatorsResponse,
    TeamOvertimeResponse,
    WellbeingScoreResponse,
    WorkloadAnalysisPayload,
    WorkloadAnalysisResponse,
)
from app.services.employee_health_service import EmployeeHealthService

router = APIRouter(prefix="/ai/employee-health", tags=["AI Employee Health"])


async def get_employee_health_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmployeeHealthService:
    return EmployeeHealthService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeHealthDashboardResponse],
    summary="Get AI Employee Health Dashboard KPIs",
)
async def get_health_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[EmployeeHealthDashboardResponse]:
    """Retrieve dynamic health KPIs: Wellbeing Score, Burnout Risk Index, Avg Workload, Total Overtime Hours, High Risk Employees, Healthy Employee %, and frontend thunk fields (wellbeingScore, burnoutRisk, avgWorkload, otHours)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id, department_id=department_id)
    return APIResponse[EmployeeHealthDashboardResponse](
        success=True,
        message="Employee health dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/wellbeing-score",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WellbeingScoreResponse],
    summary="Get Wellbeing Score",
)
async def get_wellbeing_score(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[WellbeingScoreResponse]:
    """Retrieve organization wellbeing score breakdown across attendance, leave usage, workload, overtime, and stress signals."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_wellbeing_score(company_id=company_id)
    return APIResponse[WellbeingScoreResponse](
        success=True,
        message="Wellbeing score fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/burnout-risk",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BurnoutRiskResponse],
    summary="Get Burnout Risk Analysis",
)
async def get_burnout_risk(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[BurnoutRiskResponse]:
    """Retrieve overall burnout index, high risk headcount, and per-employee risk evaluations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_burnout_risk(company_id=company_id)
    return APIResponse[BurnoutRiskResponse](
        success=True,
        message="Burnout risk analysis fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/workload-analysis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WorkloadAnalysisResponse],
    summary="Get Workload Analysis",
)
async def get_workload_analysis(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[WorkloadAnalysisResponse]:
    """Retrieve average weekly workload hours, capacity utilization %, overloaded & underutilized headcount."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_workload_analysis(company_id=company_id)
    return APIResponse[WorkloadAnalysisResponse](
        success=True,
        message="Workload analysis fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/overtime",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[OvertimeResponse],
    summary="Get Overtime Monitoring Metrics",
)
async def get_overtime(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[OvertimeResponse]:
    """Retrieve total overtime hours, daily/weekly averages, top overtime employees, and budget impact."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_overtime(company_id=company_id)
    return APIResponse[OvertimeResponse](
        success=True,
        message="Overtime monitoring metrics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/stress-indicators",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[StressIndicatorsResponse],
    summary="Get Stress Indicators",
)
async def get_stress_indicators(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[StressIndicatorsResponse]:
    """Retrieve stress index, risk category, affected employee counts, and AI stress management recommendations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_stress_indicators(company_id=company_id)
    return APIResponse[StressIndicatorsResponse](
        success=True,
        message="Stress indicators fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/burnout-trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BurnoutTrendResponse],
    summary="Get Burnout Trend",
)
async def get_burnout_trend(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[BurnoutTrendResponse]:
    """Retrieve historical weekly & monthly burnout index trends."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_burnout_trend(company_id=company_id)
    return APIResponse[BurnoutTrendResponse](
        success=True,
        message="Burnout trend fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/team-overtime",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TeamOvertimeResponse],
    summary="Get Team Overtime Breakdown",
)
async def get_team_overtime(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[TeamOvertimeResponse]:
    """Retrieve department and team overtime hours breakdown."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_team_overtime(company_id=company_id)
    return APIResponse[TeamOvertimeResponse](
        success=True,
        message="Team overtime fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeHealthAnalyticsResponse],
    summary="Get Employee Health Analytics",
)
async def get_health_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[EmployeeHealthAnalyticsResponse]:
    """Retrieve overall wellness trends, burnout risk distribution, overtime distribution, and workload distribution."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_analytics(company_id=company_id)
    return APIResponse[EmployeeHealthAnalyticsResponse](
        success=True,
        message="Employee health analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/employee/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeHealthDetailResponse],
    summary="Get Employee Health Details",
)
async def get_employee_health_detail(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[EmployeeHealthDetailResponse]:
    """Retrieve specific employee wellbeing score, burnout risk level, weekly workload, and overtime hours."""
    data = await service.get_employee_health_detail(employee_id=employee_id)
    return APIResponse[EmployeeHealthDetailResponse](
        success=True,
        message="Employee health details fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeHealthDashboardResponse],
    summary="Analyze Employee Health via AI",
)
async def analyze_health(
    payload: AnalyzeHealthPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[EmployeeHealthDashboardResponse]:
    """Trigger AI LLM health and wellbeing evaluation."""
    company_id = get_company_id_from_claims(claims)
    data = await service.analyze_health(company_id=company_id)
    return APIResponse[EmployeeHealthDashboardResponse](
        success=True,
        message="Employee health analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/burnout-analysis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BurnoutRiskResponse],
    summary="Run AI Burnout Analysis",
)
async def analyze_burnout(
    payload: BurnoutAnalysisPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[BurnoutRiskResponse]:
    """Run AI burnout risk analysis engine for attendance and overtime patterns."""
    company_id = get_company_id_from_claims(claims)
    data = await service.analyze_burnout(company_id=company_id)
    return APIResponse[BurnoutRiskResponse](
        success=True,
        message="Burnout analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/workload-analysis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WorkloadAnalysisResponse],
    summary="Run AI Workload Analysis",
)
async def analyze_workload(
    payload: WorkloadAnalysisPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[WorkloadAnalysisResponse]:
    """Run AI workload distribution analysis."""
    company_id = get_company_id_from_claims(claims)
    data = await service.analyze_workload(company_id=company_id)
    return APIResponse[WorkloadAnalysisResponse](
        success=True,
        message="Workload analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate-insights",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[StressIndicatorsResponse],
    summary="Generate AI Health Insights",
)
async def generate_health_insights(
    payload: GenerateInsightsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeHealthService, Depends(get_employee_health_service)],
) -> APIResponse[StressIndicatorsResponse]:
    """Generate AI health insights, stress alerts, and wellness action plans."""
    company_id = get_company_id_from_claims(claims)
    data = await service.generate_insights(company_id=company_id)
    return APIResponse[StressIndicatorsResponse](
        success=True,
        message="Health insights generated successfully.",
        data=data,
        errors=None,
    )
