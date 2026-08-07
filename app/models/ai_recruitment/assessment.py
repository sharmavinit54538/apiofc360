"""CodingAssessmentRecord database model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CodingAssessmentRecord(Base):
    """Coding challenge and candidate submission evaluation."""

    __tablename__ = "coding_assessment_records"
    __table_args__ = (
        Index("ix_coding_assessment_application", "application_id"),
        Index("ix_coding_assessment_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    language: Mapped[str] = mapped_column(String(30), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="INTERMEDIATE")
    topic: Mapped[str] = mapped_column(String(100), nullable=False, default="General")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))

    challenge: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Challenge spec
    candidate_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Evaluation result

    # Quick-access scores
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pass_fail: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")

    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
