"""AIRecruitmentInterviewSession database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recruitment import Application


class AIRecruitmentInterviewSession(Base):
    """AI-powered interview session with transcript and scorecard."""

    __tablename__ = "ai_recruitment_interview_sessions"
    __table_args__ = (
        Index("ix_rec_ai_interview_application", "application_id"),
        Index("ix_rec_ai_interview_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    interview_type: Mapped[str] = mapped_column(String(20), nullable=False, default="TEXT")  # TEXT|VOICE|VIDEO
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="INTERMEDIATE")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))

    # Questions and answers
    questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evaluations: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Aggregated scores
    technical_knowledge_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    communication_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    problem_solving_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    leadership_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    analytical_thinking_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    teamwork_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    overall_interview_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Summary
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    hiring_recommendation: Mapped[str] = mapped_column(String(20), nullable=False, default="REVIEW")
    red_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    positive_highlights: Mapped[list | None] = mapped_column(JSON, nullable=True)

    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    application: Mapped["Application"] = relationship("Application", lazy="select")
