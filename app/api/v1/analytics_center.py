"""FastAPI router for AI Analytics Center endpoints (/api/v1/ai/analytics/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.analytics_center import (
    AnalyticsDashboardData,
    AnalyticsGeneratePayload,
    AnalyticsKPIsResponse,
    AnalyticsPredictPayload,
    AttritionPredictionResponse,
    ComplianceAnalyticsResponse,
    ExecutiveSummaryResponse,
    HeadcountForecastResponse,
    HealthAnalyticsResponse,
    HiringDemandResponse,
    PayrollTrendResponse,
    PerformanceAnalyticsResponse,
    RecruitmentAnalyticsResponse,
    SkillGapResponse,
    WorkforceAnalyticsResponse,
)
from app.schemas.auth import APIResponse
from app.services.analytics_center_service import AnalyticsCenterService

router = APIRouter(prefix="/ai/analytics", tags=["AI Analytics Center"])


async def get_analytics_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnalyticsCenterService:
    return AnalyticsCenterService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalyticsDashboardData],
    summary="Get Complete AI Insights Dashboard Data",
)
async def get_analytics_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[AnalyticsDashboardData]:
    """Retrieve full AI Insights Dashboard dataset expected by frontend thunk fetchAIInsightsDashboard and selectors (kpis, summary, headcountForecast, hiringDemand, payrollTrend, skillGap, recruitment, performance, employeeHealth, compliance, attrition, charts)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[AnalyticsDashboardData](
        success=True,
        message="AI Analytics dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/kpis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalyticsKPIsResponse],
    summary="Get Executive Analytics KPIs",
)
async def get_analytics_kpis(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[AnalyticsKPIsResponse]:
    """Retrieve executive KPIs: Workforce Health Score, Attrition Risk, Hiring Efficiency, Payroll Health, Compliance Score, Productivity Index."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_kpis(company_id=company_id)
    return APIResponse[AnalyticsKPIsResponse](
        success=True,
        message="Analytics KPIs fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/headcount-forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HeadcountForecastResponse],
    summary="Get Headcount Forecast",
)
async def get_headcount_forecast(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[HeadcountForecastResponse]:
    """Retrieve monthly/quarterly predictive headcount growth forecasts."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_headcount_forecast(company_id=company_id)
    return APIResponse[HeadcountForecastResponse](
        success=True,
        message="Headcount forecast fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/hiring-demand",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HiringDemandResponse],
    summary="Get Department Hiring Demand",
)
async def get_hiring_demand(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[HiringDemandResponse]:
    """Retrieve department-wise hiring demand, velocity, and cost estimates."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_hiring_demand(company_id=company_id)
    return APIResponse[HiringDemandResponse](
        success=True,
        message="Hiring demand fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/payroll-trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollTrendResponse],
    summary="Get Payroll Trends & Forecast",
)
async def get_payroll_trend(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[PayrollTrendResponse]:
    """Retrieve monthly payroll trends, overtime costs, forecast costs, and budget variance."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_payroll_trend(company_id=company_id)
    return APIResponse[PayrollTrendResponse](
        success=True,
        message="Payroll trend fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/skill-gap",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SkillGapResponse],
    summary="Get Skill Gap Analysis",
)
async def get_skill_gap(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[SkillGapResponse]:
    """Retrieve organizational skill gaps and training course recommendations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_skill_gap(company_id=company_id)
    return APIResponse[SkillGapResponse](
        success=True,
        message="Skill gap analysis fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/recruitment",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RecruitmentAnalyticsResponse],
    summary="Get Recruitment Intelligence",
)
async def get_recruitment_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[RecruitmentAnalyticsResponse]:
    """Retrieve recruitment pipeline health, offer acceptance rates, and candidate quality scores."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_recruitment(company_id=company_id)
    return APIResponse[RecruitmentAnalyticsResponse](
        success=True,
        message="Recruitment analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/performance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PerformanceAnalyticsResponse],
    summary="Get Performance Intelligence",
)
async def get_performance_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[PerformanceAnalyticsResponse]:
    """Retrieve performance metrics, top/low performers count, and promotion readiness %."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_performance(company_id=company_id)
    return APIResponse[PerformanceAnalyticsResponse](
        success=True,
        message="Performance analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/workforce",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[WorkforceAnalyticsResponse],
    summary="Get Workforce Intelligence",
)
async def get_workforce_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[WorkforceAnalyticsResponse]:
    """Retrieve workforce utilization rate, productivity score, and health score."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_workforce(company_id=company_id)
    return APIResponse[WorkforceAnalyticsResponse](
        success=True,
        message="Workforce analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HealthAnalyticsResponse],
    summary="Get Employee Health Analytics",
)
async def get_health_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[HealthAnalyticsResponse]:
    """Retrieve burnout risks, wellbeing score, and workload analysis."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_health(company_id=company_id)
    return APIResponse[HealthAnalyticsResponse](
        success=True,
        message="Employee health analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/compliance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceAnalyticsResponse],
    summary="Get Compliance Analytics",
)
async def get_compliance_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[ComplianceAnalyticsResponse]:
    """Retrieve compliance score, open risks, missing docs, and audit readiness %."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_compliance(company_id=company_id)
    return APIResponse[ComplianceAnalyticsResponse](
        success=True,
        message="Compliance analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/attrition",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttritionPredictionResponse],
    summary="Get Attrition Prediction Metrics",
)
async def get_attrition_prediction(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[AttritionPredictionResponse]:
    """Retrieve high risk employees list, flight risk scores, and department attrition trends."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_attrition(company_id=company_id)
    return APIResponse[AttritionPredictionResponse](
        success=True,
        message="Attrition prediction metrics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExecutiveSummaryResponse],
    summary="Get AI Executive Summary",
)
async def get_executive_summary(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[ExecutiveSummaryResponse]:
    """Retrieve AI-generated executive summary, key insights, risks, and recommendations."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_summary(company_id=company_id)
    return APIResponse[ExecutiveSummaryResponse](
        success=True,
        message="Executive summary fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalyticsDashboardData],
    summary="Trigger Analytics Computation",
)
async def generate_analytics(
    payload: AnalyticsGeneratePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[AnalyticsDashboardData]:
    """Trigger manual computation of AI analytics snapshot."""
    company_id = get_company_id_from_claims(claims)
    data = await service.generate_analytics(payload=payload, company_id=company_id)
    return APIResponse[AnalyticsDashboardData](
        success=True,
        message="Analytics computation completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/predict",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[HeadcountForecastResponse],
    summary="Run Predictive Model Simulation",
)
async def predict_analytics(
    payload: AnalyticsPredictPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AnalyticsCenterService, Depends(get_analytics_service)],
) -> APIResponse[HeadcountForecastResponse]:
    """Run AI predictive headcount simulation."""
    company_id = get_company_id_from_claims(claims)
    data = await service.predict_analytics(payload=payload, company_id=company_id)
    return APIResponse[HeadcountForecastResponse](
        success=True,
        message="Predictive simulation completed successfully.",
        data=data,
        errors=None,
    )
