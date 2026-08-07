"""Document audit logs database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class DocumentAuditLog(Base):
    """Secure document access and action audit trail."""

    __tablename__ = "document_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    action: Mapped[str] = mapped_column(String(50), nullable=False)  # UPLOAD, UPDATE, DELETE, SIGN, VERIFY, VIEW
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)  # EMPLOYEE_DOC, COMPANY_DOC, TEMPLATE
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="select")
