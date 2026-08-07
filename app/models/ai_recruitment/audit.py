"""RecruitmentAuditLog database model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecruitmentAuditLog(Base):
    """Full audit trail for all user actions."""

    __tablename__ = "recruitment_audit_logs"
    __table_args__ = (
        Index("ix_rec_audit_log_user", "user_id"),
        Index("ix_rec_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_rec_audit_log_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    action: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE, UPDATE, DELETE, VIEW, LOGIN, etc.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'Job', 'Application', etc.
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    meta_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
