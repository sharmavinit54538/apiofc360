"""AI Shift Planner models."""
from __future__ import annotations
from datetime import date, datetime, time
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, Time, Enum as SQLEnum, func, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.employee import Employee

import enum


class ShiftPlanStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ShiftPlanSource(str, enum.Enum):
    AI = "AI"
    MANUAL = "MANUAL"


class ShiftType(str, enum.Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    MORNING = "MORNING"
    EVENING = "EVENING"
    OVERTIME = "OVERTIME"
    ROTATION = "ROTATION"
    HOLIDAY = "HOLIDAY"
    OFF = "OFF"
    WEEKLY_OFF = "WEEKLY_OFF"
    LEAVE = "LEAVE"
    TRAINING = "TRAINING"
    WFH = "WFH"


class EntryApprovalStatus(str, enum.Enum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class ShiftPlan(Base):
    __tablename__ = "shift_plans"
    __table_args__ = (
        Index("ix_shift_plans_company_id", "company_id"),
        Index("ix_shift_plans_status", "status"),
        CheckConstraint("period_end >= period_start", name="ck_shift_plans_period"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan_type: Mapped[str] = mapped_column(String(30), nullable=False)  # WEEKLY, MONTHLY, ROTATION, HOLIDAY
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ShiftPlanStatus] = mapped_column(SQLEnum(ShiftPlanStatus), nullable=False, default=ShiftPlanStatus.DRAFT)
    source: Mapped[ShiftPlanSource] = mapped_column(SQLEnum(ShiftPlanSource), nullable=False, default=ShiftPlanSource.MANUAL)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_optimization_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    company: Mapped[Company] = relationship("Company", lazy="select")
    entries: Mapped[list[ShiftPlanEntry]] = relationship("ShiftPlanEntry", back_populates="plan", cascade="all, delete-orphan", lazy="select")

class ShiftPlanEntry(Base):
    __tablename__ = "shift_plan_entries"
    __table_args__ = (
        Index("ix_shift_plan_entries_plan_id", "plan_id"),
        Index("ix_shift_plan_entries_employee_id", "employee_id"),
        Index("ix_shift_plan_entries_shift_date", "shift_date"),
        Index("ix_shift_plan_entries_company_id", "company_id"),
        Index("ix_shift_plan_entries_approval", "approval_status"),
        UniqueConstraint("plan_id", "employee_id", "shift_date", name="uq_shift_plan_entry_plan_emp_date"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("shift_plans.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_type: Mapped[ShiftType] = mapped_column(SQLEnum(ShiftType), nullable=False)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    approval_status: Mapped[EntryApprovalStatus] = mapped_column(SQLEnum(EntryApprovalStatus), nullable=False, default=EntryApprovalStatus.APPROVED)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[ShiftPlan] = relationship("ShiftPlan", back_populates="entries")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
