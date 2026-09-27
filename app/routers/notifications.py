"""Notifications router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.core_modules.misc_service import TopLevelMiscService

router = APIRouter(prefix="/notifications", tags=["Core - Notifications"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


@router.get("")
@router.get("/")
async def list_user_notifications(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = TopLevelMiscService(session)
    items = await srv.list_notifications(uid, unread_only=False)
    return _ok(items)


@router.get("/unread")
async def list_unread_notifications(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = TopLevelMiscService(session)
    items = await srv.list_notifications(uid, unread_only=True)
    return _ok(items)
