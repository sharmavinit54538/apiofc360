"""Notifications router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Core - Notifications"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> uuid.UUID:
    co_id = claims.get("company_id")
    if not co_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No company association found in token claims.",
        )
    try:
        return uuid.UUID(str(co_id))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid company ID format in claims.",
        )


def _get_uid(claims: dict) -> uuid.UUID:
    raw_uid = claims.get("sub") or claims.get("user_id") or claims.get("id")
    if not raw_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity missing in token claims.",
        )
    try:
        return uuid.UUID(str(raw_uid))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format in claims.",
        )


class ReadAllPayload(BaseModel):
    category: Optional[str] = None


class ReadManyPayload(BaseModel):
    ids: List[uuid.UUID]


# ── Static routes (Must be declared before dynamic /{id}/... routes) ────────


@router.get("/unread-count")
async def get_unread_count(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    counts = await notification_service.get_unread_count(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
    )
    return _ok(counts)


@router.get("/unread")
async def list_legacy_unread_notifications(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    res = await notification_service.list_notifications(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        unread=True,
        limit=50,
    )
    return _ok(res["items"])


@router.post("/read-all")
async def mark_all_read(
    payload: Optional[ReadAllPayload] = Body(default=None),
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    category = payload.category if payload else None
    res = await notification_service.mark_all_read(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        category=category,
    )
    return _ok(res, message="All notifications marked as read")


@router.post("/read")
async def mark_many_read(
    payload: ReadManyPayload,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    res = await notification_service.mark_many_read(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        notification_ids=payload.ids,
    )
    return _ok(res, message="Notifications marked as read")


# ── Listing (Root) ─────────────────────────────────────────────────────────


@router.get("")
@router.get("/")
async def list_notifications(
    cursor: Optional[str] = Query(default=None, description="Cursor for pagination"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    unread: Optional[bool] = Query(default=None, description="Filter by unread status"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    priority: Optional[str] = Query(default=None, description="Filter by priority"),
    module: Optional[str] = Query(default=None, description="Filter by module"),
    include_archived: bool = Query(
        default=False,
        alias="includeArchived",
        description="Include archived notifications",
    ),
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    result = await notification_service.list_notifications(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        cursor=cursor,
        limit=limit,
        unread=unread,
        category=category,
        priority=priority,
        module=module,
        include_archived=include_archived,
    )
    return _ok(result)


# ── Dynamic Item Routes ───────────────────────────────────────────────────


@router.post("/{id}/read")
async def mark_notification_read(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    item = await notification_service.mark_read(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        notification_id=id,
    )
    return _ok(item, message="Notification marked as read")


@router.post("/{id}/unread")
async def mark_notification_unread(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    item = await notification_service.mark_unread(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        notification_id=id,
    )
    return _ok(item, message="Notification marked as unread")


@router.post("/{id}/archive")
async def archive_notification(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)
    item = await notification_service.archive_notification(
        session,
        company_id=company_id,
        recipient_id=recipient_id,
        notification_id=id,
    )
    return _ok(item, message="Notification archived")
