"""Database models for AI Emotion Aware Chatbot system.

Tracks employee support chats, classified emotion labels, and calibrated reply scripts.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.company import Company


class EmotionAwareChatSession(Base):
    """Dialogue session tracking channel for employee support conversations."""

    __tablename__ = "emotion_aware_chat_sessions"
    __table_args__ = (
        Index("ix_emotion_chat_sessions_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    company: Mapped[Company] = relationship("Company", lazy="select")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    messages: Mapped[list[EmotionAwareChatMessage]] = relationship("EmotionAwareChatMessage", back_populates="session", cascade="all, delete-orphan", lazy="select")


class EmotionAwareChatMessage(Base):
    """Dialogue history entries with classified sentiment tags."""

    __tablename__ = "emotion_aware_chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("emotion_aware_chat_sessions.id", ondelete="CASCADE"), nullable=False)

    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # USER, SYSTEM
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_emotion: Mapped[str] = mapped_column(String(30), nullable=False, default="NEUTRAL")  # HAPPY, ANGRY, SAD, FRUSTRATED, STRESSED, BURNOUT, EXCITED, NEUTRAL

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    session: Mapped[EmotionAwareChatSession] = relationship("EmotionAwareChatSession", back_populates="messages")
