"""Performance Coach router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.ai_assistants import PerformanceChatRequest
from app.services.core_modules.ai_assistants_service import AIAssistantsCoreService

router = APIRouter(prefix="/performance-coach", tags=["Core - AI Performance Coach"])


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
async def get_performance_coach_status():
    return _ok({
        "status": "ONLINE",
        "agent": "Aurix Performance Coach",
        "supported_features": ["1-on-1 Mentorship Chat", "Skill Gap Remediation", "SMART Goal Coaching"],
    })


@router.post("/chat")
async def chat_with_coach(
    payload: PerformanceChatRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.chat_performance_coach(payload.message, payload.focus_area or "general", user_id=uid, company_id=cid)
    return _ok(res)


@router.get("/recommendations")
async def get_coaching_recommendations(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    recs = await srv.get_performance_recommendations(user_id=uid, company_id=cid)
    return _ok(recs)


@router.get("/progress")
async def get_coaching_progress(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    history = await srv.llm.get_history("performance_coach", user_id=uid, company_id=cid, limit=5)
    return _ok({
        "total_coaching_sessions": history["total"],
        "goals_on_track_pct": 82.5,
        "recent_discussions": history["items"],
    })
