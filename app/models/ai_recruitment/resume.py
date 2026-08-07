"""AIResumeDocument database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class AIResumeDocument(Base):
    """Extended resume document with AI parsing results and embedding reference."""

    __tablename__ = "ai_resume_documents"
    __table_args__ = (
        Index("ix_ai_resume_doc_application", "application_id"),
        Index("ix_ai_resume_doc_candidate", "candidate_id"),
        Index("ix_ai_resume_doc_status", "parse_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True)

    # File metadata
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="pdf")

    # OCR / Parsing
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    ocr_engine_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Quick-access extracted fields
    candidate_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    candidate_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    years_experience: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Vector store reference
    embedding_indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    # Audit
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    uploader: Mapped["User | None"] = relationship("User", lazy="select")
