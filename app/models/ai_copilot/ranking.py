"""Candidate consolidated ranking score database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recruitment import Job
    from app.models.ai_copilot.document import ResumeDocument


class CandidateRanking(Base):
    """Consolidated ranking scores."""

    __tablename__ = "candidate_rankings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    overall_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    technical_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    experience_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    education_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    project_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    certification_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    communication_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    leadership_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    culture_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    learning_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    resume_document: Mapped[ResumeDocument] = relationship("ResumeDocument", back_populates="rankings")
    job: Mapped[Job] = relationship("Job", lazy="select")
