"""Document comparison run database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Index, JSON, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ai_document_analysis.document import AnalyzedDocument


class DocumentComparisonRun(Base):
    """Logs comparison output and score matches between two documents."""

    __tablename__ = "document_comparison_runs"
    __table_args__ = (
        Index("ix_doc_comparisons_left", "source_document_id"),
        Index("ix_doc_comparisons_right", "target_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analyzed_documents.id", ondelete="CASCADE"), nullable=False)
    target_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("analyzed_documents.id", ondelete="CASCADE"), nullable=False)

    similarity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    differences: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Structured JSON of differences
    missing_info: Mapped[list | None] = mapped_column(JSON, nullable=True)
    changed_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fraud_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)

    compared_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_document: Mapped[AnalyzedDocument] = relationship("AnalyzedDocument", foreign_keys=[source_document_id], lazy="select")
    target_document: Mapped[AnalyzedDocument] = relationship("AnalyzedDocument", foreign_keys=[target_document_id], lazy="select")
