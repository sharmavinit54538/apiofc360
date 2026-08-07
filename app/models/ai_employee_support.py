"""Database models for the Employee Support Ticket system.

Includes support tickets, status updates, and audit trail for resolution.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class SupportTicket(Base):
    """Represents a logged employee support or IT ticket."""

    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_employee", "employee_id"),
        Index("ix_support_tickets_status", "status"),
        Index("ix_support_tickets_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    category: Mapped[str] = mapped_column(String(50), nullable=False)  # IT, HR, PAYROLL, GENERAL
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"))  # LOW, MEDIUM, HIGH, URGENT
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default=text("'OPEN'"))  # OPEN, IN_PROGRESS, CLOSED, ESCALATED

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    assigned_owner: Mapped[User | None] = relationship("User", foreign_keys=[assigned_to], lazy="select")
    updates: Mapped[list[TicketUpdate]] = relationship("TicketUpdate", back_populates="ticket", cascade="all, delete-orphan", lazy="select")


class TicketUpdate(Base):
    """Tracks updates, comments, and state changes for a ticket."""

    __tablename__ = "support_ticket_updates"
    __table_args__ = (
        Index("ix_ticket_updates_ticket", "ticket_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    update_text: Mapped[str] = mapped_column(Text, nullable=False)
    status_changed_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    ticket: Mapped[SupportTicket] = relationship("SupportTicket", back_populates="updates")
    author: Mapped[User | None] = relationship("User", foreign_keys=[updated_by], lazy="select")
