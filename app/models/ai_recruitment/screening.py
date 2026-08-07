"""AIScreeningResult database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recruitment import Application


class AIScreeningResult(Base):
    """AI screening decision for a candidate-job pair."""

    __tablename__ = "ai_screening_results"
    __table_args__ = (
        Index("ix_screening_application", "application_id"),
        Index("ix_screening_decision", "decision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    resume_document_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_resume_documents.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # SHORTLIST|REVIEW|REJECT
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    auto_action_taken: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    # Analysis JSON
    strengths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    weaknesses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    risk_analysis: Mapped[list | None] = mapped_column(JSON, nullable=True)
    red_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    green_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hiring_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    hr_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    questions_to_ask: Mapped[list | None] = mapped_column(JSON, nullable=True)

    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    application: Mapped["Application"] = relationship("Application", lazy="select")
