"""Managers router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager, _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.core_modules.misc_service import ManagersService

router = APIRouter(prefix="/managers", tags=["Core - Managers"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/team")
async def get_manager_team(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = ManagersService(session)
    team = await srv.get_team(uid, cid)
    return _ok(team)


@router.get("/dashboard")
async def get_manager_dashboard(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    uid = _uid(claims)
    cid = _get_cid(claims)
    srv = ManagersService(session)
    dash = await srv.get_manager_dashboard(uid, cid)
    return _ok(dash)
