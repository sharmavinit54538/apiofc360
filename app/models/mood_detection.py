"""AI Mood Detection Engine model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class MoodDetectionLog(Base):
    __tablename__ = "mood_detection_logs"
    __table_args__ = (Index("ix_mood_logs_employee_id", "employee_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    input_source: Mapped[str] = mapped_column(String(30), nullable=False)  # CHAT, VOICE, FEEDBACK, SURVEY, REVIEW
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_mood: Mapped[str] = mapped_column(String(30), nullable=False)  # STRESSED, BURNOUT, DISENGAGED, MOTIVATED, SATISFIED
    confidence_score: Mapped[int | None] = mapped_column(None, nullable=True)
    wellness_recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
