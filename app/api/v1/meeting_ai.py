"""FastAPI router for AI Meeting Intelligence endpoints (/api/v1/ai/meeting/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.meeting_ai import (
    ActionItemsResponse,
    AnalyzeMeetingPayload,
    DiscussionAnalyticsResponse,
    ExtractActionItemsPayload,
    FollowUpsResponse,
    GenerateFollowupsPayload,
    MeetingDashboardResponse,
    MeetingDetailResponse,
    MeetingSummariesResponse,
    MeetingSummaryItem,
    MeetingVolumeResponse,
    SummarizeMeetingPayload,
    TeamInsightsResponse,
)
from app.services.meeting_ai_service import MeetingAIService

router = APIRouter(prefix="/ai/meeting", tags=["AI Meeting Intelligence"])


async def get_meeting_ai_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MeetingAIService:
    return MeetingAIService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingDashboardResponse],
    summary="Get AI Meeting Intelligence Dashboard KPIs",
)
async def get_meeting_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingDashboardResponse]:
    """Retrieve dynamic meeting intelligence KPIs: Meetings Analyzed, Action Items, Open Follow-ups, Avg Duration, Volume Charts, Summaries, Team Insights, and Discussion Analytics supporting frontend thunk fetchMeetingIntelligence."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[MeetingDashboardResponse](
        success=True,
        message="Meeting intelligence dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/summaries",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingSummariesResponse],
    summary="Get AI Meeting Summaries",
)
async def get_meeting_summaries(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingSummariesResponse]:
    """Retrieve AI-generated meeting executive summaries, key decisions, highlights, risks, blockers, and next steps."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_summaries(company_id=company_id)
    return APIResponse[MeetingSummariesResponse](
        success=True,
        message="Meeting summaries fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/action-items",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ActionItemsResponse],
    summary="Get Extracted Action Items",
)
async def get_action_items(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[ActionItemsResponse]:
    """Retrieve extracted action items with assigned owners, due dates, priorities, and status."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_action_items(company_id=company_id)
    return APIResponse[ActionItemsResponse](
        success=True,
        message="Action items fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/follow-ups",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[FollowUpsResponse],
    summary="Get Follow-up Tracking Metrics",
)
async def get_follow_ups(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[FollowUpsResponse]:
    """Retrieve pending, completed, overdue, and upcoming follow-up tasks."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_follow_ups(company_id=company_id)
    return APIResponse[FollowUpsResponse](
        success=True,
        message="Follow-ups fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/team-insights",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TeamInsightsResponse],
    summary="Get Team Participation & Engagement Insights",
)
async def get_team_insights(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[TeamInsightsResponse]:
    """Retrieve participation %, speaking time, engagement score, collaboration score, and meeting sentiment."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_team_insights(company_id=company_id)
    return APIResponse[TeamInsightsResponse](
        success=True,
        message="Team insights fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/discussion-analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DiscussionAnalyticsResponse],
    summary="Get Discussion Topic Analytics",
)
async def get_discussion_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[DiscussionAnalyticsResponse]:
    """Retrieve topics discussed, topic frequency, time spent per topic, recurring topics, and AI insights."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_discussion_analytics(company_id=company_id)
    return APIResponse[DiscussionAnalyticsResponse](
        success=True,
        message="Discussion analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/volume",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingVolumeResponse],
    summary="Get Meeting Volume Analytics",
)
async def get_meeting_volume(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingVolumeResponse]:
    """Retrieve daily, weekly, monthly, department, and team meeting volume distributions."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_volume_analytics(company_id=company_id)
    return APIResponse[MeetingVolumeResponse](
        success=True,
        message="Meeting volume analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingSummariesResponse],
    summary="Get Analyzed Meetings History",
)
async def get_meeting_history(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingSummariesResponse]:
    """Retrieve historical analyzed meetings list."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history(company_id=company_id)
    return APIResponse[MeetingSummariesResponse](
        success=True,
        message="Meeting history fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/{meeting_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingDetailResponse],
    summary="Get Specific Meeting Details",
)
async def get_meeting_detail(
    meeting_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingDetailResponse]:
    """Retrieve specific meeting transcript, summary, action items, decisions, and MOM."""
    data = await service.get_meeting_detail(meeting_id=meeting_id)
    return APIResponse[MeetingDetailResponse](
        success=True,
        message="Meeting details fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingDashboardResponse],
    summary="Analyze Meeting via AI Engine",
)
async def analyze_meeting(
    payload: AnalyzeMeetingPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingDashboardResponse]:
    """Trigger AI LLM meeting transcript analysis, extracting executive summary, action items, decisions, and MOM."""
    company_id = get_company_id_from_claims(claims)
    data = await service.analyze_meeting(payload=payload, company_id=company_id)
    return APIResponse[MeetingDashboardResponse](
        success=True,
        message="Meeting analyzed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/summarize",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MeetingSummaryItem],
    summary="Generate AI Meeting Summary",
)
async def summarize_meeting(
    payload: SummarizeMeetingPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[MeetingSummaryItem]:
    """Generate executive summary, key decisions, and next steps for meeting transcript."""
    data = await service.summarize_meeting(payload=payload)
    return APIResponse[MeetingSummaryItem](
        success=True,
        message="Meeting summary generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/extract-action-items",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ActionItemsResponse],
    summary="Extract Action Items from Transcript",
)
async def extract_action_items(
    payload: ExtractActionItemsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[ActionItemsResponse]:
    """Extract action items, tasks, owners, and due dates from transcript text."""
    data = await service.extract_action_items(payload=payload)
    return APIResponse[ActionItemsResponse](
        success=True,
        message="Action items extracted successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/generate-followups",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[FollowUpsResponse],
    summary="Generate Follow-up Reminders",
)
async def generate_followups(
    payload: GenerateFollowupsPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[MeetingAIService, Depends(get_meeting_ai_service)],
) -> APIResponse[FollowUpsResponse]:
    """Generate follow-up reminder tasks from meeting transcript."""
    data = await service.generate_followups(payload=payload)
    return APIResponse[FollowUpsResponse](
        success=True,
        message="Follow-up reminders generated successfully.",
        data=data,
        errors=None,
    )
