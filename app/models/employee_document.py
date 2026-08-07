"""EmployeeDocument model, fully merged and extended for the Document Management Module."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User
    from app.models.document import (
        DocumentCategory,
        DocumentVersion,
        DocumentSignature,
        DocumentVerification,
        DocumentExpiryTracking,
    )


class EmployeeDocument(Base):
    """Employee-specific documents (Passport, Driving License, resume etc.)."""

    __tablename__ = "employee_documents"
    __table_args__ = (
        Index("ix_employee_documents_employee_id", "employee_id"),
        Index("ix_employee_documents_status", "status"),
        Index("ix_employee_documents_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    
    # Category (Nullable to support legacy non-categorized records)
    category_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("document_categories.id", ondelete="SET NULL"), nullable=True)
    
    # Uploaded by (Nullable to support legacy records)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Keep legacy document_url, document_type, document_number, is_verified, verified_by, verified_at
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)  # AADHAAR/PAN/PASSPORT/DRIVING_LICENSE/EXPERIENCE_...
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Secure local storage fields
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", server_default=text("'PENDING'"))  # PENDING, VERIFIED, REJECTED, REQUIRES_SIGNATURE
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="PRIVATE", server_default=text("'PRIVATE'"))  # PUBLIC, PRIVATE, DEPARTMENT, MANAGER_ONLY, HR_ONLY
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Audit & Soft Delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", back_populates="documents", foreign_keys=[employee_id], lazy="select")
    category: Mapped[DocumentCategory | None] = relationship("DocumentCategory", lazy="select")
    uploader: Mapped[User | None] = relationship("User", foreign_keys=[uploaded_by], lazy="select")
    
    versions: Mapped[list[DocumentVersion]] = relationship("DocumentVersion", back_populates="employee_document", cascade="all, delete-orphan", lazy="select")
    signatures: Mapped[list[DocumentSignature]] = relationship("DocumentSignature", back_populates="employee_document", cascade="all, delete-orphan", lazy="select")
    verifications: Mapped[list[DocumentVerification]] = relationship("DocumentVerification", back_populates="employee_document", cascade="all, delete-orphan", lazy="select")
    expiry_tracks: Mapped[list[DocumentExpiryTracking]] = relationship("DocumentExpiryTracking", back_populates="employee_document", cascade="all, delete-orphan", lazy="select")
