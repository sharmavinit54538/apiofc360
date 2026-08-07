"""Onboarding database models."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON, Numeric, text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompanySettings(Base):
    """Company settings database model."""

    __tablename__ = "company_settings"

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
    timezone: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    date_format: Mapped[str | None] = mapped_column(String(20))
    time_format: Mapped[str | None] = mapped_column(String(20))
    financial_year: Mapped[str | None] = mapped_column(String(20))
    week_start_day: Mapped[str | None] = mapped_column(String(20))
    working_days: Mapped[dict | None] = mapped_column(JSON)
    office_timing: Mapped[str | None] = mapped_column(String(50))
    default_shift: Mapped[str | None] = mapped_column(String(50))
    leave_policy_template: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Designation(Base):
    """Designation database model."""

    __tablename__ = "designations"

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class LeavePolicy(Base):
    """Leave policy database model."""

    __tablename__ = "leave_policies"

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    days_allowed: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class Shift(Base):
    """Shift database model."""

    __tablename__ = "shifts"

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[str] = mapped_column(String(20), nullable=False)
    end_time: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class OnboardingProgress(Base):
    """Onboarding progress database model.

    Single row per company. Acts as the authoritative source of truth for:
    - Which steps have been completed (boolean flags per step)
    - What the current active step is (current_step)
    - Last update timestamp

    Step mapping:
        1 = Company Details
        2 = Admin Profile
        3 = HR Settings
        4 = Departments
        5 = Designations
        6 = Invite Employees
        7 = Completed (dashboard)
    """

    __tablename__ = "onboarding_progress"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))

    # Per-step completion boolean flags — source of truth for idempotency/ordering
    company_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    admin_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    hr_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    departments_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    designations_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    employees_invited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    # Optional generic JSON blob for additional persisted data
    data: Mapped[dict | None] = mapped_column(JSON)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

