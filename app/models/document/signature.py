"""Document signature database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.employee_document import EmployeeDocument


class DocumentSignature(Base):
    """Employee digital signatures tracking."""

    __tablename__ = "document_signatures"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_doc_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="CASCADE"), nullable=False)
    signer_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING, SIGNED, REJECTED
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relations
    employee_document: Mapped[EmployeeDocument] = relationship("EmployeeDocument", back_populates="signatures")
    signer: Mapped[User] = relationship("User", foreign_keys=[signer_user_id], lazy="select")
