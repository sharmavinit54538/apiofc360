"""Document verification database model."""

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
    from app.models.employee_document import EmployeeDocument


class DocumentVerification(Base):
    """Document audit check approval log."""

    __tablename__ = "document_verifications"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_doc_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="CASCADE"), nullable=False)
    verifier_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    action: Mapped[str] = mapped_column(String(30), nullable=False)  # APPROVED, REJECTED, RE_UPLOAD_REQUESTED
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee_document: Mapped[EmployeeDocument] = relationship("EmployeeDocument", back_populates="verifications")
    verifier: Mapped[User] = relationship("User", foreign_keys=[verifier_user_id], lazy="select")
