"""AI HR Voice Assistant model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class VoiceCommandLog(Base):
    __tablename__ = "voice_command_logs"
    __table_args__ = (Index("ix_voice_logs_company_id", "company_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    raw_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_intent: Mapped[str | None] = mapped_column(String(100), nullable=True)   # SHOW_ATTENDANCE, GENERATE_PAYROLL, etc.
    parsed_entities: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON
    execution_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    tts_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
