"""Database models for AI Behavioural Interview Generator system.

Includes dynamic session parameters and dimensions-based evaluation logs.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company


class BehaviouralInterviewSession(Base):
    """Represents a customized dynamic behavioural interview session context."""

    __tablename__ = "behavioural_interview_sessions"
    __table_args__ = (
        Index("ix_behavioural_sessions_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    role: Mapped[str] = mapped_column(String(100), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, nullable=False)
    seniority: Mapped[str] = mapped_column(String(50), nullable=False)  # JUNIOR, MID, SENIOR, LEAD
    company_culture: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    company: Mapped[Company] = relationship("Company", lazy="select")
    questions: Mapped[list[BehaviouralInterviewQuestion]] = relationship("BehaviouralInterviewQuestion", back_populates="session", cascade="all, delete-orphan", lazy="select")


class BehaviouralInterviewQuestion(Base):
    """Dynamic STAR or dimensions behavioural questions with candidate response scoring logs."""

    __tablename__ = "behavioural_interview_questions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("behavioural_interview_sessions.id", ondelete="CASCADE"), nullable=False)

    dimension: Mapped[str] = mapped_column(String(50), nullable=False)  # STAR_METHOD, LEADERSHIP, CONFLICT_RESOLUTION, TEAMWORK, COMMUNICATION, CRITICAL_THINKING, EMOTIONAL_INTELLIGENCE
    question_text: Mapped[str] = mapped_column(Text, nullable=False)

    candidate_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Rating 1-10
    evaluation_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    session: Mapped[BehaviouralInterviewSession] = relationship("BehaviouralInterviewSession", back_populates="questions")
