"""Database models for Enterprise Employee Mental Wellness AI.

Includes wellness logs, anonymous chat pipelines, and HR escalation rules.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Numeric, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.company import Company


class EmployeeWellnessLog(Base):
    """Daily mood, sleep, stress tracker log per employee."""

    __tablename__ = "employee_wellness_logs"
    __table_args__ = (
        Index("ix_wellness_logs_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    mood_score: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 to 10 mood score
    stress_level: Mapped[str] = mapped_column(String(20), nullable=False)  # LOW, MEDIUM, HIGH
    sleep_hours: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False)
    burnout_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    logged_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")


class WellnessEscalationRule(Base):
    """Alert parameters defining critical values triggering HR alerts."""

    __tablename__ = "wellness_escalation_rules"
    __table_args__ = (
        Index("ix_wellness_rules_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    min_mood_score: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    stress_trigger_level: Mapped[str] = mapped_column(String(20), nullable=False, default="HIGH")  # HIGH, MEDIUM
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, default="ALERT_HR")  # ALERT_HR, SCHEDULE_COUNSELING
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    company: Mapped[Company] = relationship("Company", lazy="select")


class WellnessAnonymousChatSession(Base):
    """Secure coaching chat session tracking using pseudonyms."""

    __tablename__ = "wellness_anonymous_chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    alias_name: Mapped[str] = mapped_column(String(100), nullable=False)  # pseudonyms (e.g. Blue Falcon, Happy Otter)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    company: Mapped[Company] = relationship("Company", lazy="select")
    messages: Mapped[list[WellnessAnonymousChatMessage]] = relationship("WellnessAnonymousChatMessage", back_populates="session", cascade="all, delete-orphan", lazy="select")


class WellnessAnonymousChatMessage(Base):
    """Dialogue log for anonymous coaching sessions."""

    __tablename__ = "wellness_anonymous_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("wellness_anonymous_chat_sessions.id", ondelete="CASCADE"), nullable=False)

    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # USER, COACH
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=Decimal("0.00"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    session: Mapped[WellnessAnonymousChatSession] = relationship("WellnessAnonymousChatSession", back_populates="messages")
