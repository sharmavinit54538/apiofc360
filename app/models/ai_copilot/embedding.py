"""Resume and job description vector embedding database models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recruitment import Job
    from app.models.ai_copilot.document import ResumeDocument


class ResumeEmbedding(Base):
    """Candidate Resume Vector embeddings."""

    __tablename__ = "resume_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False)

    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)  # nomic-embed-text floats
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="nomic-embed-text")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    resume_document: Mapped[ResumeDocument] = relationship("ResumeDocument", back_populates="embeddings")


class JobEmbedding(Base):
    """Job description Vector embeddings."""

    __tablename__ = "job_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)  # nomic-embed-text floats
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="nomic-embed-text")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    job: Mapped[Job] = relationship("Job", lazy="select")
