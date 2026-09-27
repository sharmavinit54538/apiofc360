"""Workforce Insights router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.core_modules.misc_service import WorkforceInsightsService

router = APIRouter(prefix="/workforce-insights", tags=["Core - Workforce Insights"])


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
@router.get("/workforce")
async def get_workforce_summary(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = WorkforceInsightsService(session)
    res = await srv.get_summary(cid)
    return _ok(res)


@router.get("/headcount")
async def get_headcount_insights(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = WorkforceInsightsService(session)
    res = await srv.get_headcount_insights(cid)
    return _ok(res)


@router.get("/trends")
async def get_workforce_trends(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = WorkforceInsightsService(session)
    res = await srv.get_trends(cid)
    return _ok(res)
