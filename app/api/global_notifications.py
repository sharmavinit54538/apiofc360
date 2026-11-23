"""Tenant-scoped persistent notification and automation APIs.
Notifications endpoints are backed by real tenant-scoped UserNotification database records.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.schemas.auth import APIResponse
from app.services import notification_service

router = APIRouter(prefix="/global-notifications", tags=["Global Notification & Automation Hub"])


def _get_cid(claims: dict | None) -> uuid.UUID:
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    co_id = claims.get("company_id")
    if not co_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company association found in token.")
    try:
        return uuid.UUID(str(co_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID.")


def _get_uid(claims: dict | None) -> uuid.UUID:
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    raw_uid = claims.get("sub") or claims.get("user_id") or claims.get("id")
    if not raw_uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User identity missing in token.")
    try:
        return uuid.UUID(str(raw_uid))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID.")


class AutomationRulePayload(BaseModel):
    name: str
    trigger_event: str
    channels: List[str] = ["IN_APP", "EMAIL"]
    recipients: List[str] = ["ALL_EMPLOYEES"]
    template: str
    is_enabled: bool = True
    delay_minutes: int = 0
    retry_count: int = 3


class PreferencesPayload(BaseModel):
    sound_enabled: bool = True
    desktop_enabled: bool = True
    email_enabled: bool = True
    sms_enabled: bool = False
    push_enabled: bool = True
    do_not_disturb: bool = False
    priority_level: str = "ALL"


# ── DB-Backed Notification Endpoints (Thin Wrappers over notification_service) ─


@router.get("/notifications", response_model=APIResponse[dict], summary="Get all notifications")
@router.head("/notifications")
async def get_notifications(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    res = await notification_service.list_notifications(
        session,
        company_id=cid,
        recipient_id=uid,
        limit=50,
    )
    return success_response(
        {
            "items": res["items"],
            "unread_count": res["totalUnread"],
            "total": len(res["items"]),
        },
        "Notifications retrieved successfully.",
    )


@router.post("/notifications/{notif_id}/read", response_model=APIResponse[dict], summary="Mark notification as read")
async def mark_notification_read(
    notif_id: str,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    try:
        nid = uuid.UUID(notif_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notification ID.")
    item = await notification_service.mark_read(
        session,
        company_id=cid,
        recipient_id=uid,
        notification_id=nid,
    )
    return success_response({"id": notif_id}, "Notification marked as read.")


@router.post("/notifications/read-all", response_model=APIResponse[dict], summary="Mark all notifications as read")
async def mark_all_notifications_read(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    res = await notification_service.mark_all_read(
        session,
        company_id=cid,
        recipient_id=uid,
    )
    return success_response({"status": "SUCCESS", "updatedCount": res["updatedCount"]}, "All notifications marked as read.")


@router.delete("/notifications/{notif_id}", response_model=APIResponse[dict], summary="Delete/Archive notification")
async def delete_notification(
    notif_id: str,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    try:
        nid = uuid.UUID(notif_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notification ID.")
    await notification_service.archive_notification(
        session,
        company_id=cid,
        recipient_id=uid,
        notification_id=nid,
    )
    return success_response({"id": notif_id}, "Notification archived.")


from app.api.notification_automation import router as automation_router
router.include_router(automation_router)

# ── Notification Preferences ───────────────────────────────────────────────


@router.get("/preferences", response_model=APIResponse[dict], summary="Get notification preferences")
async def get_preferences(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    comp = await session.get(Company, cid)
    hr_settings = comp.hr_settings or {} if comp else {}
    prefs = hr_settings.get("global_notification_preferences") or {
        "sound_enabled": True,
        "desktop_enabled": True,
        "email_enabled": True,
        "sms_enabled": False,
        "push_enabled": True,
        "do_not_disturb": False,
        "priority_level": "ALL",
    }
    return success_response(prefs, "Notification preferences retrieved.")


@router.put("/preferences", response_model=APIResponse[dict], summary="Update notification preferences")
async def update_preferences(
    payload: PreferencesPayload,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    comp = await session.get(Company, cid)
    if not comp:
        raise HTTPException(status_code=404, detail="Company not found.")

    hr_settings = comp.hr_settings or {}
    hr_settings["global_notification_preferences"] = payload.model_dump()
    comp.hr_settings = hr_settings
    flag_modified(comp, "hr_settings")
    await session.commit()

    return success_response(payload.model_dump(), "Notification preferences updated successfully.")
