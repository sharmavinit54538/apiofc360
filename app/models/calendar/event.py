"""Calendar event database model."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, Time, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.calendar.reminder import EventReminder


class CalendarEvent(Base):
    """Base company calendar event posting."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        Index("ix_calendar_events_event_type", "event_type"),
        Index("ix_calendar_events_visibility", "visibility"),
        Index("ix_calendar_events_status", "status"),
        Index("ix_calendar_events_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # Holiday, Meeting, Birthday, Town Hall etc.

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)

    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="PUBLIC", server_default=text("'PUBLIC'"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))

    # Audit & Soft Delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="select")
    reminders: Mapped[list[EventReminder]] = relationship("EventReminder", back_populates="event", cascade="all, delete-orphan", lazy="select")
