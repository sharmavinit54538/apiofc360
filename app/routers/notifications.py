"""Notifications router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal, get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.notification import UserNotification
from app.services import notification_service

logger = logging.getLogger("app.routers.notifications")

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


@router.get("/stream")
async def stream_notifications(
    request: Request,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    claims: dict = Depends(get_current_user_claims),
) -> StreamingResponse:
    """Server-Sent Events (SSE) stream for real-time notification events.

    Requires Bearer token authorization header (JWT via query parameter is forbidden).
    Supported event types:
    - notification.created: emitted when a new notification is delivered
    - unread_count: total and category-wise count of unread notifications
    - ping: heartbeat event emitted every 20 seconds
    """
    if (
        request.query_params.get("token")
        or request.query_params.get("jwt")
        or request.query_params.get("access_token")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication via query string is not permitted. Use the Authorization header.",
        )

    company_id = _get_cid(claims)
    recipient_id = _get_uid(claims)

    async def event_generator() -> AsyncGenerator[str, None]:
        queue = notification_service.subscribe(recipient_id)
        try:
            # 1. Process Last-Event-ID if provided to catch up on missed notifications
            if last_event_id:
                try:
                    last_uuid = uuid.UUID(last_event_id.strip())
                    async with AsyncSessionLocal() as session:
                        ref_stmt = select(UserNotification.created_at).where(
                            UserNotification.id == last_uuid,
                            UserNotification.recipient_id == recipient_id,
                            UserNotification.company_id == company_id,
                        )
                        ref_res = await session.execute(ref_stmt)
                        last_created_at = ref_res.scalar_one_or_none()
                        if last_created_at:
                            missed_stmt = (
                                select(UserNotification)
                                .where(
                                    UserNotification.company_id == company_id,
                                    UserNotification.recipient_id == recipient_id,
                                    or_(
                                        UserNotification.created_at > last_created_at,
                                        and_(
                                            UserNotification.created_at == last_created_at,
                                            UserNotification.id != last_uuid,
                                        ),
                                    ),
                                    or_(
                                        UserNotification.expires_at.is_(None),
                                        UserNotification.expires_at > func.now(),
                                    ),
                                )
                                .order_by(UserNotification.created_at.asc(), UserNotification.id.asc())
                            )
                            missed_res = await session.execute(missed_stmt)
                            for m in missed_res.scalars().all():
                                payload = json.dumps(notification_service.serialize_notification(m))
                                yield f"id: {m.id}\nevent: notification.created\ndata: {payload}\n\n"
                except Exception as ex:
                    logger.debug("Failed processing Last-Event-ID %s: %s", last_event_id, ex)

            # 2. Emit initial unread_count
            async with AsyncSessionLocal() as session:
                counts = await notification_service.get_unread_count(
                    session, company_id=company_id, recipient_id=recipient_id
                )
                yield f"event: unread_count\ndata: {json.dumps(counts)}\n\n"

            # 3. Main event loop with 20s ping heartbeat
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"id: {item['id']}\nevent: notification.created\ndata: {json.dumps(item['data'])}\n\n"

                    # Push updated unread_count
                    async with AsyncSessionLocal() as session:
                        updated_counts = await notification_service.get_unread_count(
                            session, company_id=company_id, recipient_id=recipient_id
                        )
                        yield f"event: unread_count\ndata: {json.dumps(updated_counts)}\n\n"
                except asyncio.TimeoutError:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    yield f"event: ping\ndata: {json.dumps({'time': now_iso})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            notification_service.unsubscribe(recipient_id, queue)

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


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
