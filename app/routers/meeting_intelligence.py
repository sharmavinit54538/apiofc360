"""Meeting Intelligence router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.ai_assistants import MeetingAnalyzeRequest
from app.services.core_modules.ai_assistants_service import AIAssistantsCoreService

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
