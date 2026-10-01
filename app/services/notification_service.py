"""Database-backed, tenant-scoped notification service."""

from __future__ import annotations

import asyncio
import base64
from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Set
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.company import Company
from app.models.notification import UserNotification

logger = logging.getLogger("app.services.notification_service")

VALID_CATEGORIES: Set[str] = {
    "attendance",
    "leave",
    "payroll",
    "documents",
    "assets",
    "recruitment",
    "onboarding_exit",
    "approvals",
    "security",
    "system",
    "ai_insights",
}

VALID_PRIORITIES: Set[str] = {"low", "normal", "high", "critical"}


def _validate_link(link: str) -> str:
    """Validate that the link is an internal application path starting with '/' and not '//'."""
    clean = (link or "").strip()
    if not clean.startswith("/") or clean.startswith("//"):
        logger.warning("Notification link '%s' is not a valid internal path; sanitizing", link)
        clean = "/" + clean.lstrip("/")
        if clean.startswith("//"):
            clean = "/"
    return clean[:500]


def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Sanitize metadata to ensure no salary or sensitive PII is included."""
    if not metadata or not isinstance(metadata, dict):
        return None
    forbidden = {
        "salary",
        "ctc",
        "basic",
        "gross_pay",
        "net_pay",
        "net_salary",
        "bank_account",
        "password",
        "token",
        "secret",
        "pin",
        "ssn",
        "pan_number",
        "aadhaar",
    }
    return {k: v for k, v in metadata.items() if str(k).lower() not in forbidden}


def _encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    payload = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor_str: Optional[str]) -> Optional[tuple[datetime, uuid.UUID]]:
    if not cursor_str:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = decoded.split("|", 1)
        if len(parts) == 2:
            dt = datetime.fromisoformat(parts[0])
            item_id = uuid.UUID(parts[1])
            return dt, item_id
    except Exception as e:
        logger.debug("Failed to decode notification cursor '%s': %s", cursor_str, e)
    return None


def serialize_notification(item: UserNotification) -> Dict[str, Any]:
    """Serialize a UserNotification instance to camelCase JSON dictionary."""
    entity = None
    if item.entity_type or item.entity_id:
        entity = {
            "type": item.entity_type,
            "id": item.entity_id,
        }

    actor = None
    if item.actor_id:
        actor_name = None
        if item.actor:
            actor_name = getattr(item.actor, "name", None) or getattr(item.actor, "email", None)
        actor = {
            "id": str(item.actor_id),
            "name": actor_name,
        }

    return {
        "id": str(item.id),
        "type": item.type,
        "category": item.category,
        "module": item.module,
        "priority": item.priority,
        "title": item.title,
        "body": item.body,
        "link": item.link,
        "entity": entity,
        "actor": actor,
        "metadata": item.metadata_,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
        "readAt": item.read_at.isoformat() if item.read_at else None,
        "archivedAt": item.archived_at.isoformat() if item.archived_at else None,
    }


async def notify(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_ids: List[uuid.UUID],
    type: str,
    category: str,
    module: str,
    title: str,
    body: str,
    link: str,
    priority: str = "normal",
    entity: Optional[Any] = None,
    actor_id: Optional[uuid.UUID] = None,
    metadata: Optional[Dict[str, Any]] = None,
    dedupe_key: Optional[str] = None,
    mandatory: bool = False,
) -> List[UserNotification]:
    """Emit DB-backed, tenant-scoped notifications to recipients.
    
    Guarantees:
    - Never raises into the caller's business transaction.
    - Uses caller's session, flushes only (caller commits).
    - Respects company settings (`inAppAlerts`) unless `mandatory=True`.
    - Validates link as internal path, truncates title/body.
    - Deduplicates by dedupe_key (ON CONFLICT DO NOTHING).
    """
    try:
        if not recipient_ids:
            return []

        # Deduplicate recipient_ids preserving order
        unique_recipients = list(dict.fromkeys(recipient_ids))

        # Check company notification settings
        if not mandatory:
            comp_stmt = select(Company.hr_settings).where(Company.id == company_id)
            comp_res = await session.execute(comp_stmt)
            hr_settings = comp_res.scalar_one_or_none() or {}
            notif_cfg = hr_settings.get("notifications")
            if isinstance(notif_cfg, dict) and notif_cfg.get("inAppAlerts") is False:
                logger.info(
                    "Skipping notification %s for company %s because inAppAlerts is disabled",
                    type,
                    company_id,
                )
                return []

        safe_link = _validate_link(link)
        safe_title = (title or "").strip()[:200]
        safe_body = (body or "").strip()[:1000]
        safe_priority = priority if priority in VALID_PRIORITIES else "normal"
        safe_category = category if category in VALID_CATEGORIES else "system"
        safe_metadata = _sanitize_metadata(metadata)

        entity_type: Optional[str] = None
        entity_id: Optional[str] = None
        if isinstance(entity, dict):
            entity_type = entity.get("type")
            entity_id = entity.get("id")
        elif entity is not None:
            entity_type = getattr(entity, "type", None)
            entity_id = getattr(entity, "id", None)

        # Build records
        records_to_insert = []
        for r_id in unique_recipients:
            records_to_insert.append({
                "id": uuid.uuid4(),
                "company_id": company_id,
                "recipient_id": r_id,
                "type": type,
                "category": safe_category,
                "module": module,
                "priority": safe_priority,
                "title": safe_title,
                "body": safe_body,
                "link": safe_link,
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id is not None else None,
                "actor_id": actor_id,
                "metadata": safe_metadata,
                "dedupe_key": dedupe_key,
            })

        # Check if database dialect supports ON CONFLICT (PostgreSQL)
        bind = getattr(session, "bind", None)
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "postgresql")

        if dedupe_key and dialect_name != "postgresql":
            # For SQLite or mock sessions, filter out existing dedupe records manually
            existing_stmt = select(UserNotification.recipient_id).where(
                UserNotification.recipient_id.in_(unique_recipients),
                UserNotification.dedupe_key == dedupe_key,
            )
            existing_res = await session.execute(existing_stmt)
            existing_recipients = set(existing_res.scalars().all())
            records_to_insert = [r for r in records_to_insert if r["recipient_id"] not in existing_recipients]
            if not records_to_insert:
                return []

        if dedupe_key and dialect_name == "postgresql":
            table = UserNotification.__table__
            stmt = (
                pg_insert(table)
                .values(records_to_insert)
                .on_conflict_do_nothing(
                    index_elements=["recipient_id", "dedupe_key"],
                    index_where=text("dedupe_key IS NOT NULL"),
                )
                .returning(table.c.id)
            )
            res = await session.execute(stmt)
            inserted_ids = list(res.scalars().all())
            if inserted_ids:
                fetch_stmt = select(UserNotification).where(UserNotification.id.in_(inserted_ids))
                fetch_res = await session.execute(fetch_stmt)
                created = list(fetch_res.scalars().all())
            else:
                created = []
        else:
            created_objs = []
            for r in records_to_insert:
                obj = UserNotification(
                    id=r["id"],
                    company_id=r["company_id"],
                    recipient_id=r["recipient_id"],
                    type=r["type"],
                    category=r["category"],
                    module=r["module"],
                    priority=r["priority"],
                    title=r["title"],
                    body=r["body"],
                    link=r["link"],
                    entity_type=r["entity_type"],
                    entity_id=r["entity_id"],
                    actor_id=r["actor_id"],
                    metadata_=r["metadata"],
                    dedupe_key=r["dedupe_key"],
                )
                session.add(obj)
                created_objs.append(obj)
            created = created_objs

        await session.flush()
        for obj in created:
            try:
                broadcast_notification(
                    obj.recipient_id,
                    {"id": str(obj.id), "data": serialize_notification(obj)},
                )
            except Exception as b_err:
                logger.debug("Broadcast notification error: %s", b_err)
        return created
    except Exception as e:
        logger.warning("Failed to emit notification type=%s: %s", type, e, exc_info=True)
        return []


async def list_notifications(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
    cursor: Optional[str] = None,
    limit: int = 20,
    unread: Optional[bool] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    module: Optional[str] = None,
    include_archived: bool = False,
) -> Dict[str, Any]:
    """Retrieve notifications with cursor pagination and filtering."""
    safe_limit = max(1, min(limit, 100))

    base_conditions = [
        UserNotification.company_id == company_id,
        UserNotification.recipient_id == recipient_id,
        or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > func.now()),
    ]

    if not include_archived:
        base_conditions.append(UserNotification.archived_at.is_(None))

    if unread is True:
        base_conditions.append(UserNotification.read_at.is_(None))
    elif unread is False:
        base_conditions.append(UserNotification.read_at.isnot(None))

    if category:
        base_conditions.append(UserNotification.category == category)
    if priority:
        base_conditions.append(UserNotification.priority == priority)
    if module:
        base_conditions.append(UserNotification.module == module)

    stmt = (
        select(UserNotification)
        .options(joinedload(UserNotification.actor))
        .where(*base_conditions)
    )

    decoded_cursor = _decode_cursor(cursor)
    if decoded_cursor:
        cursor_dt, cursor_id = decoded_cursor
        stmt = stmt.where(
            or_(
                UserNotification.created_at < cursor_dt,
                and_(
                    UserNotification.created_at == cursor_dt,
                    UserNotification.id < cursor_id,
                ),
            )
        )

    stmt = stmt.order_by(UserNotification.created_at.desc(), UserNotification.id.desc()).limit(safe_limit + 1)
    res = await session.execute(stmt)
    records = list(res.scalars().all())

    has_more = len(records) > safe_limit
    items = records[:safe_limit]
    next_cursor = _encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None

    # Total unread count
    total_unread_stmt = select(func.count(UserNotification.id)).where(
        UserNotification.company_id == company_id,
        UserNotification.recipient_id == recipient_id,
        UserNotification.read_at.is_(None),
        UserNotification.archived_at.is_(None),
        or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > func.now()),
    )
    total_unread = (await session.execute(total_unread_stmt)).scalar() or 0

    return {
        "items": [serialize_notification(item) for item in items],
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "totalUnread": total_unread,
    }


async def get_unread_count(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
) -> Dict[str, Any]:
    """Get total unread notifications count and breakdown by category."""
    group_stmt = (
        select(UserNotification.category, func.count(UserNotification.id))
        .where(
            UserNotification.company_id == company_id,
            UserNotification.recipient_id == recipient_id,
            UserNotification.read_at.is_(None),
            UserNotification.archived_at.is_(None),
            or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > func.now()),
        )
        .group_by(UserNotification.category)
    )
    res = await session.execute(group_stmt)
    by_category = {cat: count for cat, count in res.all()}
    total = sum(by_category.values())

    return {
        "total": total,
        "byCategory": by_category,
    }


async def mark_read(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> Dict[str, Any]:
    """Mark a single notification as read."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(UserNotification)
        .where(
            UserNotification.id == notification_id,
            UserNotification.company_id == company_id,
            UserNotification.recipient_id == recipient_id,
        )
        .values(read_at=now)
        .returning(UserNotification)
    )
    res = await session.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    await session.commit()
    return serialize_notification(item)


async def mark_unread(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> Dict[str, Any]:
    """Mark a single notification as unread."""
    stmt = (
        update(UserNotification)
        .where(
            UserNotification.id == notification_id,
            UserNotification.company_id == company_id,
            UserNotification.recipient_id == recipient_id,
        )
        .values(read_at=None)
        .returning(UserNotification)
    )
    res = await session.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    await session.commit()
    return serialize_notification(item)


async def mark_many_read(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
    notification_ids: List[uuid.UUID],
) -> Dict[str, Any]:
    """Mark specified notifications as read."""
    if not notification_ids:
        return {"updatedCount": 0, "readAt": None}

    now = datetime.now(timezone.utc)
    stmt = (
        update(UserNotification)
        .where(
            UserNotification.id.in_(notification_ids),
            UserNotification.company_id == company_id,
            UserNotification.recipient_id == recipient_id,
            UserNotification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    res = await session.execute(stmt)
    await session.commit()
    return {"updatedCount": res.rowcount, "readAt": now.isoformat()}


async def mark_all_read(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Mark all unread notifications (optionally filtered by category) as read."""
    now = datetime.now(timezone.utc)
    conditions = [
        UserNotification.company_id == company_id,
        UserNotification.recipient_id == recipient_id,
        UserNotification.read_at.is_(None),
    ]
    if category:
        conditions.append(UserNotification.category == category)

    stmt = update(UserNotification).where(*conditions).values(read_at=now)
    res = await session.execute(stmt)
    await session.commit()
    return {"updatedCount": res.rowcount, "readAt": now.isoformat()}


async def archive_notification(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    recipient_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> Dict[str, Any]:
    """Archive a notification."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(UserNotification)
        .where(
            UserNotification.id == notification_id,
            UserNotification.company_id == company_id,
            UserNotification.recipient_id == recipient_id,
        )
        .values(archived_at=now)
        .returning(UserNotification)
    )
    res = await session.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Notification not found")
    await session.commit()
    return serialize_notification(item)


# ── Live SSE Broadcast Subscription Management ──────────────────────────────

_subscribers: Dict[uuid.UUID, Set[asyncio.Queue]] = defaultdict(set)


def subscribe(recipient_id: uuid.UUID) -> asyncio.Queue:
    """Subscribe a recipient queue to live notification events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[recipient_id].add(q)
    return q


def unsubscribe(recipient_id: uuid.UUID, q: asyncio.Queue) -> None:
    """Unsubscribe a recipient queue."""
    if recipient_id in _subscribers:
        _subscribers[recipient_id].discard(q)
        if not _subscribers[recipient_id]:
            del _subscribers[recipient_id]


def broadcast_notification(recipient_id: uuid.UUID, item: Dict[str, Any]) -> None:
    """Broadcast an event payload to all active subscriber queues for a recipient."""
    queues = _subscribers.get(recipient_id)
    if queues:
        for q in list(queues):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass
