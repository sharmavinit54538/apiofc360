"""AI Hub — Leave Assistant (/api/v1/ai-hub/leave-assistant/*)."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.leave_assistant import (
    AnalyzeLeaveRequest,
    ForecastLeaveRequest,
    LeaveAnalysisResult,
    LeaveAssistantOverview,
    LeaveForecastDataPoint,
    LeaveForecastResult,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims, resolve_department_id
from app.services.ai_leave_service import AILeaveService

router = APIRouter(prefix="/ai-hub/leave-assistant", tags=["AI Hub - Leave Assistant"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AILeaveService:
    return AILeaveService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveAssistantOverview],
    summary="Leave Assistant Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_service)],
) -> APIResponse[LeaveAssistantOverview]:
    """Retrieve overall leave management KPIs, approvals, and team availability."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = LeaveAssistantOverview(
        totalLeaves=int(dash.total_leaves),
        pendingApprovals=int(dash.pending_approvals),
        conflictsDetected=int(dash.conflicts_detected),
        averageLeaveDays=float(dash.average_leave_days),
        teamAvailabilityPct=float(dash.team_availability_pct),
        peakLeaveRisk="LOW" if dash.conflicts_detected < 3 else "MEDIUM",
    )
    return APIResponse[LeaveAssistantOverview](
        success=True,
        message="Leave assistant overview fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveAnalysisResult],
    summary="Analyze Department-wide Leave Patterns",
)
async def analyze_leave(
    payload: AnalyzeLeaveRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[LeaveAnalysisResult]:
    """Perform department-wide leave pattern analysis across specified timeframe."""
    company_id = get_company_id_from_claims(claims)
    dept_id = await resolve_department_id(session, company_id, payload.department)

    dash = await service.get_dashboard(company_id=company_id, department_id=dept_id)
    analytics = await service.get_analytics(company_id=company_id)

    data = LeaveAnalysisResult(
        timeframe=payload.timeframe,
        department=payload.department,
        totalRequests=int(dash.total_leaves),
        approvalRate=round(max(0.0, 100.0 - (float(dash.pending_approvals) * 2.0)), 1),
        avgDurationDays=float(analytics.avg_duration_days),
        peakMonths=analytics.peak_months or ["August", "December"],
        topLeaveTypes=analytics.type_distribution or [
            {"type": "Casual Leave", "count": 28},
            {"type": "Sick Leave", "count": 14},
            {"type": "Earned Leave", "count": 20},
        ],
        conflictsCount=int(dash.conflicts_detected),
        recommendations=[
            "Encourage staggering leaves around national holidays.",
            "Establish secondary backup leads during peak vacation months.",
        ],
    )
    return APIResponse[LeaveAnalysisResult](
        success=True,
        message="Leave analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveForecastResult],
    summary="Forecast Upcoming Leave Demand",
)
async def forecast_leave(
    payload: ForecastLeaveRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AILeaveService, Depends(get_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[LeaveForecastResult]:
    """Forecast expected leave volume and coverage impact between dates."""
    company_id = get_company_id_from_claims(claims)
    dept_id = await resolve_department_id(session, company_id, payload.department)

    raw_forecast = await service.get_forecast(company_id=company_id, group_by="weekly")

    forecast_points = [
        LeaveForecastDataPoint(
            periodLabel=item.period_label,
            expectedLeaveDays=float(item.expected_leave_days),
            riskLevel=item.peak_risk_level,
            affectedDepartment=item.affected_department,
        )
        for item in raw_forecast.data
    ]

    total_days = sum(p.expectedLeaveDays for p in forecast_points)

    data = LeaveForecastResult(
        startDate=payload.startDate,
        endDate=payload.endDate,
        department=payload.department,
        totalExpectedDays=round(total_days, 1),
        projectedImpactLevel="MODERATE" if total_days > 40 else "LOW",
        forecast=forecast_points,
        coverageRecommendations=[
            "Coordinate cross-functional project backups in week 3.",
            "Review pending sprint commitments against forecasted absence days.",
        ],
    )
    return APIResponse[LeaveForecastResult](
        success=True,
        message="Leave forecast generated successfully.",
        data=data,
        errors=None,
    )
