"""Resume documents and extracted data database models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recruitment import Application
    from app.models.ai_copilot.embedding import ResumeEmbedding
    from app.models.ai_copilot.match import CandidateSimilarity, CandidateAiAnalysis
    from app.models.ai_copilot.ranking import CandidateRanking
    from app.models.ai_copilot.question import InterviewQuestion


class ResumeDocument(Base):
    """Uploaded resume file document details."""

    __tablename__ = "resume_documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    application: Mapped[Application] = relationship("Application", lazy="select")
    extracted_data: Mapped[list[ResumeExtractedData]] = relationship("ResumeExtractedData", back_populates="resume_document", cascade="all, delete-orphan", lazy="select")
    embeddings: Mapped[list[ResumeEmbedding]] = relationship("ResumeEmbedding", back_populates="resume_document", cascade="all, delete-orphan", lazy="select")
    similarities: Mapped[list[CandidateSimilarity]] = relationship("CandidateSimilarity", back_populates="resume_document", cascade="all, delete-orphan", lazy="select")
    ai_analyses: Mapped[list[CandidateAiAnalysis]] = relationship("CandidateAiAnalysis", back_populates="resume_document", cascade="all, delete-orphan", lazy="select")
    rankings: Mapped[list[CandidateRanking]] = relationship("CandidateRanking", back_populates="resume_document", cascade="all, delete-orphan", lazy="select")
    interview_questions: Mapped[list[InterviewQuestion]] = relationship("InterviewQuestion", back_populates="resume_document", cascade="all, delete-orphan", lazy="select")


class ResumeExtractedData(Base):
    """Structured Extracted JSON details from Resume."""

    __tablename__ = "resume_extracted_data"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_document_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("resume_documents.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(150), nullable=True)

    linkedin_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON lists/maps of extracted values
    skills: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"programming_languages": [...], "frameworks": [...]}
    experience: Mapped[list | None] = mapped_column(JSON, nullable=True)  # List of jobs
    education: Mapped[list | None] = mapped_column(JSON, nullable=True)  # List of education records
    projects: Mapped[list | None] = mapped_column(JSON, nullable=True)  # List of projects
    certifications: Mapped[list | None] = mapped_column(JSON, nullable=True)  # List of certifications

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    resume_document: Mapped[ResumeDocument] = relationship("ResumeDocument", back_populates="extracted_data")
