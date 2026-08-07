"""SQLAlchemy model for Google Document AI OCR Records."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin


class DocumentOCRRecord(Base, TenantMixin):
    """Stores metadata, Google Document AI OCR extraction result, form fields, tables, and raw response JSON."""

    __tablename__ = "document_ocr_records"
    __table_args__ = (
        Index("ix_doc_ocr_company_id", "company_id"),
        Index("ix_doc_ocr_status", "status"),
        Index("ix_doc_ocr_document_type", "document_type"),
        Index("ix_doc_ocr_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="processing")  # processing, completed, failed
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # JSON structures for extracted components
    entities: Mapped[dict | list] = mapped_column(JSONB, nullable=False, default=list)
    tables: Mapped[dict | list] = mapped_column(JSONB, nullable=False, default=list)
    form_fields: Mapped[dict | list] = mapped_column(JSONB, nullable=False, default=list)
    pages: Mapped[dict | list] = mapped_column(JSONB, nullable=False, default=list)
    raw_response: Mapped[dict | list] = mapped_column(JSONB, nullable=False, default=dict)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_summary_dict(self) -> dict:
        """Helper to return clean summary dictionary."""
        return {
            "document_id": str(self.id),
            "status": self.status,
            "page_count": self.page_count,
            "text": self.extracted_text,
            "confidence": round(self.confidence, 4) if self.confidence else 0.0,
            "entities": self.entities or [],
            "tables": self.tables or [],
            "form_fields": self.form_fields or [],
            "pages": self.pages or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
