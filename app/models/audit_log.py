"""Audit log database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, event, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


PII_UNMASK_ACCESS = "PII_UNMASK_ACCESS"


class AuditLog(Base):
    """Audit log for security-sensitive operations (logins, password resets, role changes)."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped[User | None] = relationship("User", lazy="select")


def create_audit_entry(
    action: str,
    company_id: uuid.UUID | None,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    details: str | None = None,
    actor_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata_json: str | None = None,
) -> AuditLog:
    """Standardized factory to guarantee company_id and required metadata are captured on all security and data events."""
    return AuditLog(
        id=uuid.uuid4(),
        action=action,
        company_id=company_id,
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
        actor_id=actor_id or (str(user_id) if user_id else None),
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=metadata_json,
    )


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _prevent_pii_unmask_audit_tampering(mapper, connection, target: AuditLog) -> None:
    """PII disclosure events are append-only and cannot be edited or deleted."""
    from sqlalchemy import inspect

    history = inspect(target).attrs.action.history
    original_action = history.deleted[0] if history.deleted else target.action
    if target.action == PII_UNMASK_ACCESS or original_action == PII_UNMASK_ACCESS:
        raise ValueError("PII_UNMASK_ACCESS audit events are immutable")

