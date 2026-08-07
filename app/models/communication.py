"""Internal Communication database models."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    String, Text, Time, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Announcement(Base):
    """Broadcast announcements and notices."""

    __tablename__ = "announcements"
    __table_args__ = (
        Index("ix_announcements_status", "status"),
        Index("ix_announcements_is_deleted", "is_deleted"),
        Index("ix_announcements_publish_date", "publish_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # General, Policy, Event, Notice
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")  # LOW, MEDIUM, HIGH, URGENT

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="ALL_EMPLOYEES")  # ALL_EMPLOYEES, DEPARTMENT etc.

    publish_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))  # DRAFT, PUBLISHED, ARCHIVED

    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Soft Delete & Audit
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by], lazy="select")
    reads: Mapped[list[AnnouncementRead]] = relationship("AnnouncementRead", back_populates="announcement", cascade="all, delete-orphan", lazy="select")


class AnnouncementRead(Base):
    """Tracks read status receipts of announcements."""

    __tablename__ = "announcement_reads"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    announcement_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    announcement: Mapped[Announcement] = relationship("Announcement", back_populates="reads")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="select")


class CompanyNews(Base):
    """Company news articles."""

    __tablename__ = "company_news"
    __table_args__ = (
        Index("ix_company_news_status", "status"),
        Index("ix_company_news_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    headline: Mapped[str] = mapped_column(String(150), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # Business, Achievement, Tech etc.

    author_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)

    publish_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))  # DRAFT, PUBLISHED, ARCHIVED
    views_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    # Soft Delete & Audit
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    author: Mapped[User] = relationship("User", foreign_keys=[author_id], lazy="select")


class CompanyEvent(Base):
    """Events organised by the company."""

    __tablename__ = "company_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    event_title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # Town Hall, Festival, Training etc.

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    organizer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)

    max_participants: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SCHEDULED", server_default=text("'SCHEDULED'"))  # SCHEDULED, COMPLETED, CANCELLED

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    organizer: Mapped[User] = relationship("User", foreign_keys=[organizer_id], lazy="select")
    registrations: Mapped[list[EventRegistration]] = relationship("EventRegistration", back_populates="event", cascade="all, delete-orphan", lazy="select")


class EventRegistration(Base):
    """Employee event registration checklist logs."""

    __tablename__ = "event_registrations"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company_events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    event: Mapped[CompanyEvent] = relationship("CompanyEvent", back_populates="registrations")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="select")


class Poll(Base):
    """System survey polls."""

    __tablename__ = "polls"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    question: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    allow_multiple_selection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anonymous_voting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_audience: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default=text("'OPEN'"))  # OPEN, CLOSED

    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by], lazy="select")
    options: Mapped[list[PollOption]] = relationship("PollOption", back_populates="poll", cascade="all, delete-orphan", lazy="select")
    votes: Mapped[list[PollVote]] = relationship("PollVote", back_populates="poll", cascade="all, delete-orphan", lazy="select")


class PollOption(Base):
    """Available option selection items for polls."""

    __tablename__ = "poll_options"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    poll_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_text: Mapped[str] = mapped_column(String(150), nullable=False)

    # Relations
    poll: Mapped[Poll] = relationship("Poll", back_populates="options")
    votes: Mapped[list[PollVote]] = relationship("PollVote", back_populates="option", cascade="all, delete-orphan", lazy="select")


class PollVote(Base):
    """Submitted vote records on options."""

    __tablename__ = "poll_votes"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    poll_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False)

    # Nullable to support anonymous voting
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    poll: Mapped[Poll] = relationship("Poll", back_populates="votes")
    option: Mapped[PollOption] = relationship("PollOption", back_populates="votes")
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id], lazy="select")


class NotificationCenter(Base):
    """Notification Center alerts logging."""

    __tablename__ = "notification_center"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    recipient: Mapped[User] = relationship("User", foreign_keys=[recipient_id], lazy="select")


class CommunicationAuditLog(Base):
    """Auditing logs of communication edits, views, and votes."""

    __tablename__ = "communication_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    action: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE, UPDATE, DELETE, PUBLISH, VOTE, REGISTER
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ANNOUNCEMENT, NEWS, EVENT, POLL
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="select")
