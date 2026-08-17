"""FastAPI router for OFC360 Reports APIs (/api/v1/reports/*).

Provides production endpoints for:
- Engagement & eNPS Analytics
- Culture & D&I Telemetry
- Survey Management
"""

from __future__ import annotations

import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.reports import (
    CultureBreakdownItem,
    CultureFeedbackData,
    CultureTelemetryData,
    CultureTrendItem,
    EngagementBreakdownItem,
    EngagementSummaryData,
    EngagementSurveyListResponse,
    EngagementTrendItem,
    EnpsTrendItem,
)
from app.services.reports_service import ReportsService

router = APIRouter(
    prefix="/reports",
    tags=["Reports Management v1"],
    dependencies=[Depends(require_admin_or_manager)],
)


def get_company_id_from_claims(claims: dict) -> uuid.UUID:
    """Extract and validate company context from authenticated JWT claims."""
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    if not co_id_str:
        # If user is superadmin without company_id in token, require explicit tenant or raise
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company context missing in user authentication claims.",
        )
    try:
        return uuid.UUID(str(co_id_str))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid company ID format in authentication claims.",
        )


async def get_reports_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReportsService:
    """Dependency provider for ReportsService."""
    return ReportsService(session=session)


# ==============================================================================
# 1. ENGAGEMENT ENDPOINTS
# ==============================================================================

@router.get(
    "/engagement/summary",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EngagementSummaryData],
    summary="Get Company Engagement Summary Metrics",
)
async def get_engagement_summary(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
) -> APIResponse[EngagementSummaryData]:
    """Retrieve real PostgreSQL-derived company engagement metrics including eNPS, participation rate, and response rate."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_engagement_summary(company_id=company_id)
    return APIResponse[EngagementSummaryData](
        success=True,
        message="Engagement summary retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/engagement/trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[EngagementTrendItem]],
    summary="Get Engagement Historical Trends",
)
async def get_engagement_trend(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
    period: str = Query("6m", description="Time period filter: 3m | 6m | 12m"),
) -> APIResponse[List[EngagementTrendItem]]:
    """Retrieve historical engagement scores and response rates across time periods."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_engagement_trends(company_id=company_id, period=period)
    return APIResponse[List[EngagementTrendItem]](
        success=True,
        message="Engagement trends retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/engagement/enps-trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[EnpsTrendItem]],
    summary="Get eNPS Historical Trends",
)
async def get_enps_trend(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
    period: str = Query("6m", description="Time period filter: 3m | 6m | 12m"),
) -> APIResponse[List[EnpsTrendItem]]:
    """Retrieve historical monthly eNPS scores calculated from real survey/wellness responses."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_enps_trends(company_id=company_id, period=period)
    return APIResponse[List[EnpsTrendItem]](
        success=True,
        message="eNPS trends retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/engagement/breakdown",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[EngagementBreakdownItem]],
    summary="Get Engagement Breakdown by Department",
)
async def get_engagement_breakdown(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
    dimension: str = Query("department", description="Breakdown dimension (department)"),
) -> APIResponse[List[EngagementBreakdownItem]]:
    """Retrieve engagement metrics broken down across company departments."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_engagement_breakdown(company_id=company_id)
    return APIResponse[List[EngagementBreakdownItem]](
        success=True,
        message="Engagement breakdown retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/engagement/surveys",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EngagementSurveyListResponse],
    summary="List Engagement Surveys & Polls",
)
async def get_engagement_surveys(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (OPEN, CLOSED, ALL)"),
    search: Optional[str] = Query(None, description="Search term in survey question/title"),
) -> APIResponse[EngagementSurveyListResponse]:
    """Retrieve paginated survey list with real participation and response statistics."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_engagement_surveys(
        company_id=company_id,
        page=page,
        limit=limit,
        status_filter=status_filter,
        search=search,
    )
    return APIResponse[EngagementSurveyListResponse](
        success=True,
        message="Engagement surveys retrieved successfully.",
        data=data,
        errors=None,
    )


# ==============================================================================
# 2. CULTURE & D&I TELEMETRY ENDPOINTS
# ==============================================================================

@router.get(
    "/culture/telemetry",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CultureTelemetryData],
    summary="Get Organizational Culture & D&I Telemetry",
)
async def get_culture_telemetry(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
) -> APIResponse[CultureTelemetryData]:
    """Retrieve real culture telemetry including belonging score, manager effectiveness, and demographic distributions."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_culture_telemetry(company_id=company_id)
    return APIResponse[CultureTelemetryData](
        success=True,
        message="Culture telemetry retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/culture/trend",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[CultureTrendItem]],
    summary="Get Culture Historical Trends",
)
async def get_culture_trend(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
    period: str = Query("6m", description="Time period filter: 3m | 6m | 12m"),
) -> APIResponse[List[CultureTrendItem]]:
    """Retrieve historical monthly culture and belonging score trends."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_culture_trends(company_id=company_id, period=period)
    return APIResponse[List[CultureTrendItem]](
        success=True,
        message="Culture trends retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/culture/breakdown",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[CultureBreakdownItem]],
    summary="Get Culture Breakdown by Department",
)
async def get_culture_breakdown(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
    dimension: str = Query("department", description="Breakdown dimension (department)"),
) -> APIResponse[List[CultureBreakdownItem]]:
    """Retrieve culture metrics broken down across company departments."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_culture_breakdown(company_id=company_id)
    return APIResponse[List[CultureBreakdownItem]](
        success=True,
        message="Culture breakdown retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/culture/feedback",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CultureFeedbackData],
    summary="Get Aggregated Culture & Feedback Analytics",
)
async def get_culture_feedback(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ReportsService, Depends(get_reports_service)],
) -> APIResponse[CultureFeedbackData]:
    """Retrieve aggregated, sanitized employee sentiment distribution and themes without exposing individual PII."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_culture_feedback(company_id=company_id)
    return APIResponse[CultureFeedbackData](
        success=True,
        message="Culture feedback analytics retrieved successfully.",
        data=data,
        errors=None,
    )
