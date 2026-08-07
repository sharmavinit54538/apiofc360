"""Database models for Timesheets and Timesheet Entries."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, Numeric, String, Text, func, text
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class Timesheet(Base):
    """Weekly timesheet submission record."""

    __tablename__ = "timesheets"
    __table_args__ = (
        Index("ix_timesheets_employee_id", "employee_id"),
        Index("ix_timesheets_week_start_date", "week_start_date"),
        Index("ix_timesheets_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False)  # Monday of the week
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))  # DRAFT, PENDING, APPROVED, REJECTED
    
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
    approved_by: Mapped[User | None] = relationship("User", lazy="select")
    entries: Mapped[list[TimesheetEntry]] = relationship("TimesheetEntry", back_populates="timesheet", cascade="all, delete-orphan", lazy="selectin")


class TimesheetEntry(Base):
    """Log entry for a specific project within a timesheet week."""

    __tablename__ = "timesheet_entries"
    __table_args__ = (
        Index("ix_timesheet_entries_timesheet_id", "timesheet_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timesheet_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("timesheets.id", ondelete="CASCADE"), nullable=False)
    
    project_id: Mapped[str] = mapped_column(String(100), nullable=False)  # E.g. proj_aurix_core
    
    monday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    tuesday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    wednesday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    thursday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    friday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    saturday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    sunday_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal('0.00'), server_default=text("0.00"))
    
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    timesheet: Mapped[Timesheet] = relationship("Timesheet", back_populates="entries")
