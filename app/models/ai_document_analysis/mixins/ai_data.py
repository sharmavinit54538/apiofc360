"""AI extraction and audit column mixin."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func, text, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class DocumentAIDataMixin:
    """AI classification, compliance summary, and verification check details."""

    classification: Mapped[str | None] = mapped_column(String(50), nullable=True)  # INVOICE, CONTRACT, etc.
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Summarization
    summary_executive: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_detailed: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_highlights: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_info: Mapped[list | None] = mapped_column(JSON, nullable=True)
    compliance_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_recommendations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    health_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Validation Results
    validation_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNVALIDATED", server_default=text("'UNVALIDATED'"))

    embedding_indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
