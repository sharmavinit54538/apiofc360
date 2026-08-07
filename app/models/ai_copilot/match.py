"""Candidate semantic match and qualitative assessment database models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recruitment import Job
    from app.models.ai_copilot.document import ResumeDocument


class CandidateSimilarity(Base):
    """Cosine semantic match outputs."""

    __tablename__ = "candidate_similarity"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)  # Cosine matching score
    matching_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])
    missing_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    resume_document: Mapped[ResumeDocument] = relationship("ResumeDocument", back_populates="similarities")
    job: Mapped[Job] = relationship("Job", lazy="select")


class CandidateAiAnalysis(Base):
    """AI Qualitative assessment evaluation from Llama3."""

    __tablename__ = "candidate_ai_analysis"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    professional_summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])
    weaknesses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])
    risk_factors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])

    hiring_recommendation: Mapped[str] = mapped_column(String(50), nullable=False)  # Strong Hire, Hire, Maybe, Reject
    culture_fit: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_fit: Mapped[str | None] = mapped_column(Text, nullable=True)
    communication_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    career_progression: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])
    upskilling_suggestions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=[])

    confidence_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.85)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    resume_document: Mapped[ResumeDocument] = relationship("ResumeDocument", back_populates="ai_analyses")
    job: Mapped[Job] = relationship("Job", lazy="select")
