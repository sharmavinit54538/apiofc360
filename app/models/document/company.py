"""Company documents database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.document.category import DocumentCategory
    from app.models.document.version import DocumentVersion


class CompanyDocument(Base):
    """Company-wide policies & NDAs."""

    __tablename__ = "company_documents"
    __table_args__ = (
        Index("ix_company_documents_category_id", "category_id"),
        Index("ix_company_documents_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    category_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("document_categories.id", ondelete="CASCADE"), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)

    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="PUBLIC", server_default=text("'PUBLIC'"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PUBLISHED", server_default=text("'PUBLISHED'"))

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    category: Mapped[DocumentCategory] = relationship("DocumentCategory", lazy="select")
    uploader: Mapped[User] = relationship("User", foreign_keys=[uploaded_by], lazy="select")
    versions: Mapped[list[DocumentVersion]] = relationship("DocumentVersion", back_populates="company_document", cascade="all, delete-orphan", lazy="select")
