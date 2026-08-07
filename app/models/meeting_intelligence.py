"""AI Meeting Intelligence model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class MeetingIntelligenceLog(Base):
    __tablename__ = "meeting_intelligence_logs"
    __table_args__ = (Index("ix_meeting_intel_company_id", "company_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    meeting_title: Mapped[str] = mapped_column(String(200), nullable=False)
    meeting_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_items: Mapped[str | None] = mapped_column(Text, nullable=True)     # JSON
    decisions: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON
    task_assignments: Mapped[str | None] = mapped_column(Text, nullable=True) # JSON
    mom: Mapped[str | None] = mapped_column(Text, nullable=True)              # Minutes of Meeting
    followup_reminders: Mapped[str | None] = mapped_column(Text, nullable=True) # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
