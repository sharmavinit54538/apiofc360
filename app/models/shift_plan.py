"""AI Shift Planner models."""
from __future__ import annotations
from datetime import date, datetime, time
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.employee import Employee

class ShiftPlan(Base):
    __tablename__ = "shift_plans"
    __table_args__ = (Index("ix_shift_plans_company_id", "company_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan_type: Mapped[str] = mapped_column(String(30), nullable=False)  # WEEKLY, MONTHLY, ROTATION, HOLIDAY
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    ai_optimization_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    company: Mapped[Company] = relationship("Company", lazy="select")
    entries: Mapped[list[ShiftPlanEntry]] = relationship("ShiftPlanEntry", back_populates="plan", cascade="all, delete-orphan", lazy="select")

class ShiftPlanEntry(Base):
    __tablename__ = "shift_plan_entries"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("shift_plans.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_type: Mapped[str] = mapped_column(String(30), nullable=False)  # DAY, NIGHT, OVERTIME, ROTATION, HOLIDAY, OFF
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[ShiftPlan] = relationship("ShiftPlan", back_populates="entries")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
