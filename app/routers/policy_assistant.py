"""Policy Assistant router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.ai_assistants import AIQueryRequest
from app.services.core_modules.ai_assistants_service import AIAssistantsCoreService

router = APIRouter(prefix="/policy-assistant", tags=["Core - AI Policy Assistant"])


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
async def get_policy_assistant_status():
    return _ok({
        "status": "ONLINE",
        "agent": "Aurix Policy AI Assistant",
        "supported_features": ["RAG Company Handbook Retrieval", "Code of Conduct Explanation", "Compliance Guidance"],
    })


@router.post("/query")
async def query_policy_assistant(
    payload: AIQueryRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    res = await srv.query_policy(payload.query, user_id=uid, company_id=cid)
    return _ok(res)


@router.get("/policies")
async def list_policies(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = AIAssistantsCoreService(session)
    policies = await srv.list_policies(cid)
    return _ok(policies)
