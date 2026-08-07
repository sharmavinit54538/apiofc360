"""AI hiring copilot request logging database model."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiLog(Base):
    """Audit logs for all local Ollama requests."""

    __tablename__ = "ai_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # EXTRACT, EMBEDDING, ANALYZE, INTERVIEW
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_length: Mapped[int] = mapped_column(Integer, nullable=False)
    response_length: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
