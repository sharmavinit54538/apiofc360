"""Database models for the AI Interview Bot system.

Includes active candidate sessions, dynamic questions, transcript responses,
live proctoring violations, and AI-compiled scorecards.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.recruitment import Candidate, Job, InterviewRound, ScorecardSubmission


class AIInterviewSession(Base):
    """Represents an ongoing candidate AI Interview session."""

    __tablename__ = "ai_interview_sessions"
    __table_args__ = (
        Index("ix_ai_interview_sessions_candidate", "candidate_id"),
        Index("ix_ai_interview_sessions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    interview_round_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_rounds.id", ondelete="SET NULL"), nullable=True)

    interview_type: Mapped[str] = mapped_column(String(30), nullable=False)  # VOICE, VIDEO, CODING, BEHAVIORAL, TECHNICAL
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SCHEDULED", server_default=text("'SCHEDULED'"))  # SCHEDULED, IN_PROGRESS, COMPLETED, SUSPENDED_PROCTOR
    current_question_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    candidate: Mapped[Candidate] = relationship("Candidate", lazy="select")
    job: Mapped[Job] = relationship("Job", lazy="select")
    round: Mapped[InterviewRound | None] = relationship("InterviewRound", lazy="select")
    questions: Mapped[list[AIInterviewQuestionInstance]] = relationship("AIInterviewQuestionInstance", back_populates="session", cascade="all, delete-orphan", lazy="select")
    responses: Mapped[list[AIInterviewResponse]] = relationship("AIInterviewResponse", back_populates="session", cascade="all, delete-orphan", lazy="select")
    scorecard: Mapped[AIInterviewScorecard | None] = relationship("AIInterviewScorecard", back_populates="session", cascade="all, delete-orphan", lazy="select")


class AIInterviewQuestionInstance(Base):
    """Specific questions generated or assigned for a session."""

    __tablename__ = "ai_interview_questions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_interview_sessions.id", ondelete="CASCADE"), nullable=False)

    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)  # TECHNICAL, CODING, BEHAVIORAL, VOICE
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    # Relations
    session: Mapped[AIInterviewSession] = relationship("AIInterviewSession", back_populates="questions")


class AIInterviewResponse(Base):
    """Transcript response or code submissions logged by candidate."""

    __tablename__ = "ai_interview_responses"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_interview_sessions.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_interview_questions.id", ondelete="CASCADE"), nullable=False)

    candidate_response: Mapped[str] = mapped_column(Text, nullable=False)
    code_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    emotion_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"calm": 0.8, "anxious": 0.2}
    communication_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"pace_wpm": 120, "filler_words": 3}
    proctoring_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"tab_switches": 0, "gaze_deviation": false}

    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))  # Rating 1-10
    evaluation_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    session: Mapped[AIInterviewSession] = relationship("AIInterviewSession", back_populates="responses")
    question: Mapped[AIInterviewQuestionInstance] = relationship("AIInterviewQuestionInstance", lazy="select")


class AIInterviewScorecard(Base):
    """Aggregate dashboard view scorecard for the AI Interview round."""

    __tablename__ = "ai_interview_scorecards"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    interview_session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_interview_sessions.id", ondelete="CASCADE"), nullable=False)
    scorecard_submission_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("scorecard_submissions.id", ondelete="SET NULL"), nullable=True)

    anti_cheating_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"total_warnings": 2, "flagged": false}
    emotion_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"predominant": "calm", "confidence": 0.8}
    communication_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"average_pace": 130}

    final_hiring_recommendation: Mapped[str] = mapped_column(String(20), nullable=False)  # STRONG_HIRE, HIRE, MAYBE, REJECT
    overall_justification: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    session: Mapped[AIInterviewSession] = relationship("AIInterviewSession", back_populates="scorecard")
    submission: Mapped[ScorecardSubmission | None] = relationship("ScorecardSubmission", lazy="select")
