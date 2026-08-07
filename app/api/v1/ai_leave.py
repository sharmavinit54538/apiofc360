"""FastAPI router for AI Leave Assistant endpoints (/api/v1/ai/leave/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai_leave import (
    AnalyzeLeaveRequestPayload,
    ApprovalSuggestionItem,
    DetectConflictsPayload,
    ForecastLeaveRequestPayload,
    GenerateSuggestionsPayload,
    LeaveApprovalSuggestionsResponse,
    LeaveConflictsResponse,
    LeaveDashboardResponse,
    LeaveDistributionResponse,
    LeaveForecastResponse,
    LeaveRequestDetailResponse,
    LeaveTrendsResponse,
    LeaveAnalyticsResponse,
    TeamAvailabilityResponse,
)
from app.services.ai_leave_service import AILeaveService

router = APIRouter(prefix="/ai/leave", tags=["AI Leave Assistant"])


async def get_ai_leave_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AILeaveService:
    return AILeaveService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveDashboardResponse],
    summary="Get AI Leave Assistant Dashboard KPIs",
)
async def get_leave_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
    department_id: Optional[uuid.UUID] = Query(None),
) -> APIResponse[LeaveDashboardResponse]:
    """Retrieve dynamic leave KPIs: Pending Requests, Approved/Rejected Counts, Approval Suggestions, Conflicts, Team Availability %, Employees On Leave Today."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id, department_id=department_id)
    return APIResponse[LeaveDashboardResponse](
        success=True,
        message="Leave dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveForecastResponse],
    summary="Get Leave Forecast",
)
async def get_leave_forecast(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
    group_by: str = Query("weekly", description="weekly | monthly | department | team"),
) -> APIResponse[LeaveForecastResponse]:
    """Retrieve expected leave demand forecast over upcoming weeks/months with peak risk levels."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_forecast(company_id=company_id, group_by=group_by)
    return APIResponse[LeaveForecastResponse](
        success=True,
        message="Leave forecast fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/distribution",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveDistributionResponse],
    summary="Get Leave Type Distribution",
)
async def get_leave_distribution(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveDistributionResponse]:
    """Retrieve leave type distribution (Casual, Sick, Vacation, WFH, Maternity, Paternity, Loss of Pay)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_distribution(company_id=company_id)
    return APIResponse[LeaveDistributionResponse](
        success=True,
        message="Leave distribution fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/approval-suggestions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveApprovalSuggestionsResponse],
    summary="Get AI Leave Approval Suggestions",
)
async def get_approval_suggestions(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveApprovalSuggestionsResponse]:
    """Retrieve AI-generated leave approval recommendations (APPROVE, REJECT, DISCUSS, MANUAL_REVIEW) with confidence scores."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_approval_suggestions(company_id=company_id)
    return APIResponse[LeaveApprovalSuggestionsResponse](
        success=True,
        message="Leave approval suggestions fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/conflicts",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveConflictsResponse],
    summary="Get Leave Conflict Detections",
)
async def get_leave_conflicts(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveConflictsResponse]:
    """Detect leave conflicts: Same Team Overlaps, Critical Resource Shortages, Manager Unavailable, Holiday Overlaps."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_conflicts(company_id=company_id)
    return APIResponse[LeaveConflictsResponse](
        success=True,
        message="Leave conflicts fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/team-availability",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TeamAvailabilityResponse],
    summary="Get Team Availability Analysis",
)
async def get_team_availability(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[TeamAvailabilityResponse]:
    """Retrieve team availability metrics, department breakdowns, and shift capacities."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_team_availability(company_id=company_id)
    return APIResponse[TeamAvailabilityResponse](
        success=True,
        message="Team availability fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/trends",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveTrendsResponse],
    summary="Get Leave Trends",
)
async def get_leave_trends(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveTrendsResponse]:
    """Retrieve historical leave volume trends across months/quarters."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_trends(company_id=company_id)
    return APIResponse[LeaveTrendsResponse](
        success=True,
        message="Leave trends fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveAnalyticsResponse],
    summary="Get Leave Analytics Overview",
)
async def get_leave_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveAnalyticsResponse]:
    """Retrieve overall leave performance analytics, availability rates, and peak months."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_analytics(company_id=company_id)
    return APIResponse[LeaveAnalyticsResponse](
        success=True,
        message="Leave analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/request/{leave_request_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveRequestDetailResponse],
    summary="Get Leave Request Details",
)
async def get_leave_request_detail(
    leave_request_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveRequestDetailResponse]:
    """Retrieve detailed information for a specific Leave Request."""
    data = await service.get_leave_request_detail(leave_request_id=leave_request_id)
    return APIResponse[LeaveRequestDetailResponse](
        success=True,
        message="Leave request details fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ApprovalSuggestionItem],
    summary="Analyze Leave Request via AI",
)
async def analyze_leave_request(
    payload: AnalyzeLeaveRequestPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[ApprovalSuggestionItem]:
    """Trigger AI LLM analysis of a single leave application."""
    data = await service.analyze_leave_request(leave_request_id=payload.leave_request_id)
    return APIResponse[ApprovalSuggestionItem](
        success=True,
        message="Leave request analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveForecastResponse],
    summary="Generate AI Leave Demand Forecast",
)
async def forecast_leave_demand(
    payload: ForecastLeaveRequestPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveForecastResponse]:
    """Run AI forecasting model for upcoming leave demand."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_forecast(company_id=company_id)
    return APIResponse[LeaveForecastResponse](
        success=True,
        message="Leave demand forecast generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate-suggestions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveApprovalSuggestionsResponse],
    summary="Generate AI Approval Suggestions",
)
async def generate_approval_suggestions(
    payload: GenerateSuggestionsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveApprovalSuggestionsResponse]:
    """Generate batch AI approval suggestions for pending leave requests."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_approval_suggestions(company_id=company_id)
    return APIResponse[LeaveApprovalSuggestionsResponse](
        success=True,
        message="Approval suggestions generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/detect-conflicts",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveConflictsResponse],
    summary="Detect Leave Conflicts via AI",
)
async def detect_leave_conflicts(
    payload: DetectConflictsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_ai_leave_service)],
) -> APIResponse[LeaveConflictsResponse]:
    """Run AI leave conflict detector for team coverage and schedule overlap."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_conflicts(company_id=company_id)
    return APIResponse[LeaveConflictsResponse](
        success=True,
        message="Leave conflicts detected successfully.",
        data=data,
        errors=None,
    )
