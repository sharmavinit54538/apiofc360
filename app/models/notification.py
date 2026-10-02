"""User notification model for real, DB-backed, tenant-scoped notification system."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class UserNotification(Base):
    """DB-backed, tenant-scoped user notification."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        Index("ix_user_notifications_company_id", "company_id"),
        Index("ix_user_notifications_recipient_id", "recipient_id"),
        Index(
            "ix_user_notifications_recipient_read_created",
            "recipient_id",
            "read_at",
            text("created_at DESC"),
        ),
        Index(
            "uq_user_notifications_recipient_dedupe",
            "recipient_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", server_default=text("'normal'")
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    link: Mapped[str] = mapped_column(String(500), nullable=False)

    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    company: Mapped[Company] = relationship("Company", foreign_keys=[company_id], lazy="select")
    recipient: Mapped[User] = relationship("User", foreign_keys=[recipient_id], lazy="select")
    actor: Mapped[User | None] = relationship("User", foreign_keys=[actor_id], lazy="select")
