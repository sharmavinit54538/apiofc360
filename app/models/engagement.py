"""Pulse surveys, k-anonymous feedback, action plans, and recognition ledger."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin


class EngagementSurvey(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_surveys"
    __table_args__ = (Index("ix_engagement_surveys_company_status", "company_id", "status"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="ONCE", server_default=text("'ONCE'"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recurrence_parent_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_surveys.id", ondelete="SET NULL"), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    min_group_size: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default=text("5"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))

    questions: Mapped[list[EngagementQuestion]] = relationship(
        "EngagementQuestion", back_populates="survey", cascade="all, delete-orphan", lazy="select",
    )


class EngagementQuestion(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_questions"
    __table_args__ = (UniqueConstraint("survey_id", "sequence_number", name="uq_engagement_question_sequence"),)

    survey_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_surveys.id", ondelete="CASCADE"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    survey: Mapped[EngagementSurvey] = relationship("EngagementSurvey", back_populates="questions", lazy="select")


class EngagementResponse(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_responses"
    __table_args__ = (
        UniqueConstraint("survey_id", "respondent_key_hash", name="uq_engagement_survey_respondent"),
        Index("ix_engagement_responses_company_survey", "company_id", "survey_id"),
    )

    survey_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_surveys.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    respondent_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    answers: Mapped[list[EngagementAnswer]] = relationship(
        "EngagementAnswer", back_populates="response", cascade="all, delete-orphan", lazy="select",
    )


class EngagementAnswer(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_answers"
    __table_args__ = (UniqueConstraint("response_id", "question_id", name="uq_engagement_answer_question"),)

    response_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_responses.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_questions.id", ondelete="CASCADE"), nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    response: Mapped[EngagementResponse] = relationship("EngagementResponse", back_populates="answers", lazy="select")


class ManagerActionPlan(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_manager_action_plans"
    __table_args__ = (Index("ix_engagement_actions_company_status", "company_id", "status"),)

    survey_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_surveys.id", ondelete="SET NULL"), nullable=True)
    manager_employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    actions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default=text("'OPEN'"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PeerRecognition(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_peer_recognitions"
    __table_args__ = (Index("ix_peer_recognition_company_recipient", "company_id", "recipient_employee_id"),)

    sender_employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    recipient_employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="APPROVED", server_default=text("'APPROVED'"))


class RewardLedgerEntry(EnterpriseModelMixin, Base):
    __tablename__ = "engagement_reward_ledger"
    __table_args__ = (
        UniqueConstraint("recognition_id", "entry_type", name="uq_reward_ledger_recognition_type"),
        Index("ix_reward_ledger_company_employee", "company_id", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    recognition_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("engagement_peer_recognitions.id", ondelete="SET NULL"), nullable=True)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
