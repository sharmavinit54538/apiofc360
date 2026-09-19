from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import not_found, permission_denied
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.misc import Notification
from app.schemas.misc import NotificationCreate, NotificationOut
from app.services.audit_service import log_action

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(current: CurrentUser = Depends(require_permission("notifications:read")), db: AsyncSession = Depends(get_db)):
    q = select(Notification).where(Notification.tenant_id == current.tenant_id, Notification.recipient_id == current.id).order_by(Notification.created_at.desc())
    return (await db.execute(q)).scalars().all()


@router.post("", response_model=NotificationOut, status_code=201)
async def create_notification(payload: NotificationCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in ("admin", "teacher"):
        raise permission_denied()
    n = Notification(tenant_id=current.tenant_id, school_id=current.school_id, **payload.model_dump())
    db.add(n)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "notification", n.id)
    await db.commit()
    await db.refresh(n)
    return n


@router.put("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: str, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = await db.get(Notification, notification_id)
    if not n or n.tenant_id != current.tenant_id or n.recipient_id != current.id:
        raise not_found("Notification")
    n.read = True
    await db.commit()
    await db.refresh(n)
    return n
