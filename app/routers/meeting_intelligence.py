"""Meeting Intelligence router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.core_modules.ai_assistants import MeetingAnalyzeRequest
from app.services.core_modules.ai_assistants_service import AIAssistantsCoreService
from app.services.meeting_ai_service import MeetingAIService

router = APIRouter(prefix="/meeting-intelligence", tags=["Core - AI Meeting Intelligence"])


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
async def get_meeting_intelligence_status():
    return _ok({
        "status": "ONLINE",
        "agent": "Aurix Meeting Intelligence AI",
        "supported_features": ["Audio Transcript Summarization", "Action Item Extraction", "Meeting Effectiveness Scoring"],
    })


@router.post("/analyze")
async def analyze_meeting_transcript(
    payload: MeetingAnalyzeRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.analyze_meeting(payload.transcript, payload.title, user_id=uid, company_id=cid)
    return _ok(res)


@router.get("/meetings")
async def list_recent_meetings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    history = await srv.llm.get_history("meeting_intelligence", user_id=uid, company_id=cid, page=page, limit=limit)
    return _ok(history)


@router.get("/insights")
async def get_meeting_insights(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.get_meeting_insights(user_id=uid, company_id=cid)
    return _ok(res)


# =============================================================================
# Granular AI Meeting Intelligence Endpoints (Dashboard, KPI, Action Items, Volume)
# =============================================================================

@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Meeting Intelligence Dashboard",
)
@router.post(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_meeting_dashboard(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve meeting intelligence analytics dashboard."""
    cid = _get_cid(claims)
    service = MeetingAIService(session=session)
    dash = await service.get_dashboard(company_id=cid)
    dump = dash.model_dump() if hasattr(dash, "model_dump") else dict(dash)
    return APIResponse[dict](
        success=True,
        message="Meeting intelligence dashboard fetched successfully.",
        data=dump,
        errors=None,
    )


@router.get(
    "/kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Meeting Intelligence KPIs",
)
@router.post(
    "/kpi",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_meeting_kpis(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Slice and retrieve meeting intelligence KPI cards."""
    cid = _get_cid(claims)
    service = MeetingAIService(session=session)
    dash = await service.get_dashboard(company_id=cid)
    data = {
        "meetings_analyzed": dash.meetings_analyzed,
        "meetingsAnalyzed": dash.meetingsAnalyzed,
        "action_items": dash.action_items,
        "actionItems": dash.actionItems,
        "follow_ups": dash.follow_ups,
        "followUps": dash.followUps,
        "avg_duration": dash.avg_duration,
        "avgDuration": dash.avgDuration,
        "average_attendance": dash.average_attendance,
        "averageAttendance": dash.average_attendance,
        "decisions_captured": dash.decisions_captured,
        "decisionsCaptured": dash.decisions_captured,
        "completion_rate": dash.completion_rate,
        "completionRate": dash.completion_rate,
        "kpis": [
            {"key": "meetings_analyzed", "label": "Meetings Analyzed", "value": dash.meetings_analyzed, "unit": "meetings"},
            {"key": "action_items", "label": "Action Items", "value": dash.action_items, "unit": "items"},
            {"key": "follow_ups", "label": "Follow-ups", "value": dash.follow_ups, "unit": "tasks"},
            {"key": "avg_duration", "label": "Average Duration", "value": dash.avg_duration, "unit": ""},
            {"key": "decisions_captured", "label": "Decisions Captured", "value": dash.decisions_captured, "unit": "decisions"},
            {"key": "completion_rate", "label": "Completion Rate", "value": dash.completion_rate, "unit": "%"},
        ],
    }
    return APIResponse[dict](
        success=True,
        message="Meeting intelligence KPIs fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/action-items",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Meeting Intelligence Action Items",
)
@router.post(
    "/action-items",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_meeting_action_items(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve extracted meeting action items, tasks, and owners."""
    cid = _get_cid(claims)
    service = MeetingAIService(session=session)
    items_resp = await service.get_action_items(company_id=cid)
    items_dump = [item.model_dump() if hasattr(item, "model_dump") else item for item in items_resp.action_items]
    data = {
        "total_action_items": items_resp.total_action_items,
        "totalActionItems": items_resp.total_action_items,
        "action_items": items_dump,
        "actionItems": items_dump,
        "items": items_dump,
    }
    return APIResponse[dict](
        success=True,
        message="Meeting action items fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/volume",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Meeting Intelligence Volume Analytics",
)
@router.post(
    "/volume",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def get_meeting_volume_analytics(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    """Retrieve meeting frequency and volume distribution."""
    cid = _get_cid(claims)
    service = MeetingAIService(session=session)
    vol = await service.get_volume_analytics(company_id=cid)
    data = {
        "daily_meetings": vol.daily_meetings,
        "dailyMeetings": vol.daily_meetings,
        "weekly_meetings": vol.weekly_meetings,
        "weeklyMeetings": vol.weekly_meetings,
        "monthly_meetings": vol.monthly_meetings,
        "monthlyMeetings": vol.monthly_meetings,
        "department_meetings": vol.department_meetings,
        "departmentMeetings": vol.department_meetings,
        "team_meetings": vol.team_meetings,
        "teamMeetings": vol.team_meetings,
        "volume": vol.weekly_meetings,
    }
    return APIResponse[dict](
        success=True,
        message="Meeting volume analytics fetched successfully.",
        data=data,
        errors=None,
    )

