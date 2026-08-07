"""Meeting database model."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, Date, ForeignKey, String, Text, Time, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.calendar.participant import MeetingParticipant
    from app.models.calendar.reminder import EventReminder


class Meeting(Base):
    """Meetings scheduled."""

    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    meeting_title: Mapped[str] = mapped_column(String(150), nullable=False)
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)

    organizer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    meeting_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="ONLINE")  # ONLINE, OFFLINE, HYBRID
    meeting_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    office_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SCHEDULED", server_default=text("'SCHEDULED'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    organizer: Mapped[User] = relationship("User", foreign_keys=[organizer_id], lazy="select")
    participants: Mapped[list[MeetingParticipant]] = relationship("MeetingParticipant", back_populates="meeting", cascade="all, delete-orphan", lazy="select")
    reminders: Mapped[list[EventReminder]] = relationship("EventReminder", back_populates="meeting", cascade="all, delete-orphan", lazy="select")
