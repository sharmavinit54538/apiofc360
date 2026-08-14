"""OFC360 Helpdesk & Support database models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class HelpdeskTicket(Base):
    """Represents a support ticket in the OFC360 Helpdesk module."""

    __tablename__ = "helpdesk_tickets"
    __table_args__ = (
        UniqueConstraint("company_id", "ticket_number", name="uq_helpdesk_ticket_company_number"),
        Index("ix_helpdesk_tickets_company_requester_created", "company_id", "requester_id", "created_at"),
        Index("ix_helpdesk_tickets_company_status", "company_id", "status"),
        Index("ix_helpdesk_tickets_assigned_to", "assigned_to_id"),
        Index("ix_helpdesk_tickets_sla_resolution_due_at", "sla_resolution_due_at"),
        Index("ix_helpdesk_tickets_category", "category"),
        Index("ix_helpdesk_tickets_priority", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    ticket_number: Mapped[str] = mapped_column(String(50), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="Medium", server_default=text("'Medium'"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Open", server_default=text("'Open'"))

    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SLA Tracking
    sla_first_response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    company: Mapped[Company] = relationship("Company", lazy="select")
    requester: Mapped[User] = relationship("User", foreign_keys=[requester_id], lazy="select")
    assigned_to: Mapped[User | None] = relationship("User", foreign_keys=[assigned_to_id], lazy="select")

    comments: Mapped[list[HelpdeskComment]] = relationship(
        "HelpdeskComment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="HelpdeskComment.created_at.asc()",
    )
    internal_notes: Mapped[list[HelpdeskInternalNote]] = relationship(
        "HelpdeskInternalNote",
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="HelpdeskInternalNote.created_at.asc()",
    )
    attachments: Mapped[list[HelpdeskAttachment]] = relationship(
        "HelpdeskAttachment",
        back_populates="ticket",
        foreign_keys="[HelpdeskAttachment.ticket_id]",
        cascade="all, delete-orphan",
        lazy="select",
    )


class HelpdeskComment(Base):
    """Discussion comments on a support ticket."""

    __tablename__ = "helpdesk_comments"
    __table_args__ = (
        Index("ix_helpdesk_comments_ticket_created", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("helpdesk_tickets.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    ticket: Mapped[HelpdeskTicket] = relationship("HelpdeskTicket", back_populates="comments")
    author: Mapped[User] = relationship("User", foreign_keys=[author_id], lazy="select")
    attachments: Mapped[list[HelpdeskAttachment]] = relationship(
        "HelpdeskAttachment",
        back_populates="comment",
        foreign_keys="[HelpdeskAttachment.comment_id]",
        cascade="all, delete-orphan",
        lazy="select",
    )


class HelpdeskInternalNote(Base):
    """Staff-only internal notes for support tickets (never exposed to regular employees)."""

    __tablename__ = "helpdesk_internal_notes"
    __table_args__ = (
        Index("ix_helpdesk_internal_notes_ticket_created", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("helpdesk_tickets.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    ticket: Mapped[HelpdeskTicket] = relationship("HelpdeskTicket", back_populates="internal_notes")
    author: Mapped[User] = relationship("User", foreign_keys=[author_id], lazy="select")


class HelpdeskAttachment(Base):
    """Files attached to tickets or comments."""

    __tablename__ = "helpdesk_attachments"
    __table_args__ = (
        Index("ix_helpdesk_attachments_ticket_id", "ticket_id"),
        Index("ix_helpdesk_attachments_comment_id", "comment_id"),
        Index("ix_helpdesk_attachments_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("helpdesk_tickets.id", ondelete="CASCADE"), nullable=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("helpdesk_comments.id", ondelete="CASCADE"), nullable=True)
    uploader_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    ticket: Mapped[HelpdeskTicket | None] = relationship("HelpdeskTicket", back_populates="attachments", foreign_keys=[ticket_id])
    comment: Mapped[HelpdeskComment | None] = relationship("HelpdeskComment", back_populates="attachments", foreign_keys=[comment_id])
    uploader: Mapped[User] = relationship("User", foreign_keys=[uploader_id], lazy="select")


class HelpdeskFAQ(Base):
    """Knowledge base FAQs for employee and staff helpdesk."""

    __tablename__ = "helpdesk_faqs"
    __table_args__ = (
        Index("ix_helpdesk_faqs_company_category", "company_id", "category"),
        Index("ix_helpdesk_faqs_is_public", "is_public"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    category: Mapped[str] = mapped_column(String(50), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_helpful_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    company: Mapped[Company] = relationship("Company", lazy="select")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="select")
