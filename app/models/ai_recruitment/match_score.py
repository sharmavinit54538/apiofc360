"""CandidateMatchScore database model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Float, Index, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CandidateMatchScore(Base):
    """Multi-dimensional JD-Resume match score with explanations."""

    __tablename__ = "candidate_match_scores"
    __table_args__ = (
        Index("ix_match_score_resume_doc", "resume_document_id"),
        Index("ix_match_score_job", "job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_resume_documents.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)

    # Dimension scores (0.0 - 1.0)
    overall_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    skill_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    experience_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    education_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    domain_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    industry_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    location_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    salary_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    availability_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # JSON analysis
    matching_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extra_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    analysis_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[str] = mapped_column(String(20), nullable=False, default="REVIEW")

    # Audit
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    computed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    resume_document: Mapped["AIResumeDocument"] = relationship("AIResumeDocument", lazy="select")
