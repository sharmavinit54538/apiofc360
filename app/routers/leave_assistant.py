"""Leave Assistant router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.ai_assistants import AIQueryRequest, LeaveApplyNLRequest
from app.services.core_modules.ai_assistants_service import AIAssistantsCoreService

router = APIRouter(prefix="/leave-assistant", tags=["Core - AI Leave Assistant"])


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
async def get_leave_assistant_status():
    return _ok({
        "status": "ONLINE",
        "agent": "Aurix Leave Assistant",
        "supported_features": ["Natural Language Policy Queries", "One-shot Leave Application", "Leave Balance Explanations"],
    })


@router.post("/query")
async def query_leave_assistant(
    payload: AIQueryRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.query_leave(payload.query, user_id=uid, company_id=cid)
    return _ok(res)


@router.post("/apply")
async def apply_leave_natural_language(
    payload: LeaveApplyNLRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.apply_leave_nl(payload.natural_language_prompt, user_id=uid, company_id=cid)
    return _ok(res)


@router.get("/history")
async def get_leave_query_history(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.get_leave_history(user_id=uid, company_id=cid, page=page, limit=limit)
    return _ok(res)
