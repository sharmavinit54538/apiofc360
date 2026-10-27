"""Shift database models."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import uuid

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text, Time,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _default_working_days() -> list[str]:
    return ["Mon", "Tue", "Wed", "Thu", "Fri"]


class Shift(Base):
    """Shift definition with timezone-aware times and configuration."""

    __tablename__ = "shifts"
    __table_args__ = (
        # Regular indexes
        Index("ix_shifts_company_id", "company_id"),
        Index("ix_shifts_is_active", "is_active"),
        Index("ix_shifts_deleted_at", "deleted_at"),
        # Constraints
        CheckConstraint("start_time <> end_time", name="ck_shifts_start_ne_end"),
        CheckConstraint("grace_period_minutes >= 0 AND grace_period_minutes <= 120",
                        name="ck_shifts_grace_period_range"),
        CheckConstraint("break_duration_minutes >= 0 AND break_duration_minutes <= 180",
                        name="ck_shifts_break_range"),
        CheckConstraint("night_premium_percent >= 0 AND night_premium_percent <= 100",
                        name="ck_shifts_night_premium_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_overnight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_minutes: Mapped[int] = mapped_column(nullable=False, default=0)
    grace_period_minutes: Mapped[int] = mapped_column(nullable=False, default=15)
    break_duration_minutes: Mapped[int] = mapped_column(nullable=False, default=60)
    work_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=0.0)
    is_night_shift: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    night_premium_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    working_days: Mapped[list[str]] = mapped_column(JSON, nullable=False,
        default=_default_working_days)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    color: Mapped[str | None] = mapped_column(String(9), nullable=True)  # #RRGGBB or #RRGGBBAA
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def assigned_employees_count(self) -> int:
        """Count of currently assigned employees (denormalized, set by service)."""
        return getattr(self, "_assigned_employees_count", 0)


class EmployeeShiftAssignment(Base):
    """Effective-dated employee shift assignment."""

    __tablename__ = "employee_shift_assignments"
    __table_args__ = (
        Index("ix_emp_shift_assign_employee", "employee_id"),
        Index("ix_emp_shift_assign_shift", "shift_id"),
        Index("ix_emp_shift_assign_company", "company_id"),
        Index("ix_emp_shift_assign_effective", "employee_id", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ShiftChangeRequest(Base):
    """Employee shift change request."""

    __tablename__ = "shift_change_requests"
    __table_args__ = (
        Index("ix_shift_change_company_status", "company_id", "status"),
        Index("ix_shift_change_employee_created", "employee_id", "created_at"),
        Index("ix_shift_change_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_shift_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )