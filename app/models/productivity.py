"""Database models for AI Productivity Tracking Engine.

Includes logs of focus ratings, work patterns, and forecasting reports.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee


class EmployeeProductivityLog(Base):
    """Daily tracked metrics of employee focus, meetings, tasks, and idle timings."""

    __tablename__ = "employee_productivity_logs"
    __table_args__ = (
        Index("ix_productivity_logs_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    focus_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 0.00 to 100.00
    deep_work_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    idle_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    meeting_hours: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    tasks_completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    recorded_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")


class ProductivityForecastingRun(Base):
    """Local LLM compiled prediction forecast report for productivity trends and burnout warning tags."""

    __tablename__ = "productivity_forecasting_runs"
    __table_args__ = (
        Index("ix_productivity_forecasts_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    predicted_focus_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    predicted_burnout_risk: Mapped[str] = mapped_column(String(20), nullable=False)  # LOW, MEDIUM, HIGH
    ai_recommendations: Mapped[str] = mapped_column(Text, nullable=False)

    forecasted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
