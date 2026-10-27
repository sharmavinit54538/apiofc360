"""Document signature database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.employee_document import EmployeeDocument


class DocumentSignature(Base):
    """Employee digital signatures tracking."""

    __tablename__ = "document_signatures"
    __table_args__ = (
        Index(
            "uq_doc_signatures_pending_partial",
            "employee_doc_id",
            "signer_user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_doc_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="CASCADE"), nullable=False)
    signer_user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING, SIGNED, REJECTED
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signed_pdf_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signed_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="BUILT_IN", server_default=text("'BUILT_IN'"))
    provider_envelope_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    signature_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    signature_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    webhook_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audit_certificate_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee_document: Mapped[EmployeeDocument] = relationship("EmployeeDocument", back_populates="signatures")
    signer: Mapped[User] = relationship("User", foreign_keys=[signer_user_id], lazy="select")
