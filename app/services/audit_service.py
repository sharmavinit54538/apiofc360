import json

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misc import AuditLog


async def log_action(
    db: AsyncSession,
    request: Request | None,
    tenant_id: str,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    metadata: dict | None = None,
):
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(entry)
    await db.flush()
