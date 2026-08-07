"""Event reminders database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.calendar.event import CalendarEvent
    from app.models.calendar.meeting import Meeting


class EventReminder(Base):
    """Reminder timings before meetings or events."""

    __tablename__ = "event_reminders"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True)

    reminder_minutes_before: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    event: Mapped[CalendarEvent | None] = relationship("CalendarEvent", back_populates="reminders")
    meeting: Mapped[Meeting | None] = relationship("Meeting", back_populates="reminders")
