"""Document versions history database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.employee_document import EmployeeDocument
    from app.models.document.company import CompanyDocument


class DocumentVersion(Base):
    """Tracks complete upload history/version of documents."""

    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_doc_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_documents.id", ondelete="CASCADE"), nullable=True)
    company_doc_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company_documents.id", ondelete="CASCADE"), nullable=True)

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee_document: Mapped[EmployeeDocument | None] = relationship("EmployeeDocument", back_populates="versions")
    company_document: Mapped[CompanyDocument | None] = relationship("CompanyDocument", back_populates="versions")
    uploader: Mapped[User] = relationship("User", foreign_keys=[uploaded_by], lazy="select")
