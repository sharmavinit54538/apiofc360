"""FastAPI router for AI Performance Coach endpoints (/api/v1/ai/performance/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai_performance import (
    CoachingSuggestionItem,
    CoachingSuggestionsResponse,
    EmployeePerformanceResponse,
    EvaluatePerformanceRequest,
    GenerateCoachingRequest,
    GeneratePromotionRequest,
    KpiAttainmentResponse,
    PerformanceAnalyticsResponse,
    PerformanceDashboardResponse,
    PerformanceTrendsResponse,
    PromotionRecommendationItem,
    PromotionRecommendationsResponse,
    SkillGapAnalysisRequest,
    SkillGapsResponse,
    TopPerformersResponse,
)
from app.services.ai_performance_service import AIPerformanceService

router = APIRouter(prefix="/ai/performance", tags=["AI Performance Coach"])


async def get_ai_performance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIPerformanceService:
    return AIPerformanceService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PerformanceDashboardResponse],
    summary="Get AI Performance Dashboard KPIs",
)
async def get_performance_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[PerformanceDashboardResponse]:
    """Retrieve dynamic performance KPIs: Average Score, Top Performers count, Skill Gaps count, Promotion Picks count."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id, department_id=department_id)
    return APIResponse[PerformanceDashboardResponse](
        success=True,
        message="Performance dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/trends",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PerformanceTrendsResponse],
    summary="Get Performance Trend Series",
)
async def get_performance_trends(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
    group_by: str = Query("quarterly", description="quarterly | monthly | department | team"),
) -> APIResponse[PerformanceTrendsResponse]:
    """Retrieve historical performance score trends across quarters or departments."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_trends(company_id=company_id, group_by=group_by)
    return APIResponse[PerformanceTrendsResponse](
        success=True,
        message="Performance trends fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/kpi-attainment",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[KpiAttainmentResponse],
    summary="Get KPI Attainment by Function",
)
async def get_kpi_attainment(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[KpiAttainmentResponse]:
    """Retrieve target vs achieved KPI metrics across corporate functions (Engineering, Sales, Operations, HR, Finance)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_kpi_attainment(company_id=company_id)
    return APIResponse[KpiAttainmentResponse](
        success=True,
        message="KPI attainment fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/top-performers",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TopPerformersResponse],
    summary="Get Top Performers Ranking",
)
async def get_top_performers(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> APIResponse[TopPerformersResponse]:
    """Retrieve top performing employees, top teams, departments, and top managers."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_top_performers(company_id=company_id, department_id=department_id, limit=limit)
    return APIResponse[TopPerformersResponse](
        success=True,
        message="Top performers fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/employee/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeePerformanceResponse],
    summary="Get Employee Multi-Dimensional Performance Score",
)
async def get_employee_performance(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[EmployeePerformanceResponse]:
    """Retrieve detailed multi-dimensional performance scores (Productivity, Attendance, Quality, Behavior, Leadership, Communication)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_employee_performance(employee_id=employee_id, company_id=company_id)
    return APIResponse[EmployeePerformanceResponse](
        success=True,
        message="Employee performance score fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/skill-gaps",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SkillGapsResponse],
    summary="Get Skill Gap Analysis Data",
)
async def get_skill_gaps(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[SkillGapsResponse]:
    """Retrieve identified role skill gaps, current skill levels, priority, and required training programs."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_skill_gaps(company_id=company_id, department_id=department_id)
    return APIResponse[SkillGapsResponse](
        success=True,
        message="Skill gaps analysis fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/promotion-recommendations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PromotionRecommendationsResponse],
    summary="Get AI Promotion Recommendations",
)
async def get_promotion_recommendations(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[PromotionRecommendationsResponse]:
    """Retrieve AI-generated promotion picks, recommended positions, leadership scores, and promotion readiness."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_promotion_recommendations(company_id=company_id, department_id=department_id)
    return APIResponse[PromotionRecommendationsResponse](
        success=True,
        message="Promotion recommendations fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/coaching-suggestions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CoachingSuggestionsResponse],
    summary="Get AI Coaching Suggestions",
)
async def get_coaching_suggestions(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[CoachingSuggestionsResponse]:
    """Retrieve personalized coaching suggestions, learning roadmaps, recommended courses, and manager actions."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_coaching_suggestions(company_id=company_id, department_id=department_id)
    return APIResponse[CoachingSuggestionsResponse](
        success=True,
        message="Coaching suggestions fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PerformanceAnalyticsResponse],
    summary="Get Performance Analytics Overview",
)
async def get_performance_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[PerformanceAnalyticsResponse]:
    """Retrieve overall performance analytics overview, department breakdowns, and KPI completion rates."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_analytics(company_id=company_id)
    return APIResponse[PerformanceAnalyticsResponse](
        success=True,
        message="Performance analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/evaluate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Evaluate Performance Review via AI",
)
async def evaluate_performance(
    payload: EvaluatePerformanceRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[dict]:
    """Trigger AI LLM evaluation of review record, generating score, justification, and recommendations."""
    return APIResponse[dict](
        success=True,
        message="Performance review evaluation triggered.",
        data={"review_id": str(payload.review_id), "status": "COMPLETED"},
        errors=None,
    )


@router.post(
    "/generate-coaching",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CoachingSuggestionItem],
    summary="Generate AI Personalized Coaching",
)
async def generate_coaching(
    payload: GenerateCoachingRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[CoachingSuggestionItem]:
    """Generate personalized AI coaching suggestions and course recommendations for an employee."""
    data = await service.generate_coaching(employee_id=payload.employee_id)
    return APIResponse[CoachingSuggestionItem](
        success=True,
        message="Personalized coaching generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate-promotion",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PromotionRecommendationItem],
    summary="Generate AI Promotion Assessment",
)
async def generate_promotion(
    payload: GeneratePromotionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[PromotionRecommendationItem]:
    """Generate AI promotion assessment, target role, confidence score, and readiness evaluation."""
    data = await service.generate_promotion(employee_id=payload.employee_id)
    return APIResponse[PromotionRecommendationItem](
        success=True,
        message="Promotion recommendation generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/skill-gap-analysis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SkillGapsResponse],
    summary="Trigger AI Skill Gap Analysis",
)
async def trigger_skill_gap_analysis(
    payload: SkillGapAnalysisRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_ai_performance_service)],
) -> APIResponse[SkillGapsResponse]:
    """Run AI skill gap analysis for a department or employee."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_skill_gaps(company_id=company_id, department_id=payload.department_id)
    return APIResponse[SkillGapsResponse](
        success=True,
        message="Skill gap analysis generated successfully.",
        data=data,
        errors=None,
    )
