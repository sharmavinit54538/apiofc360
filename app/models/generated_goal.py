"""Database models for AI Goal Generator Engine.

Includes generated OKRs, KPIs, Team/Department goals, and performance calibrations.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.company import Company


class GeneratedGoal(Base):
    """OKR, KPI, Team, Department, or Task goals auto-generated and adjusted by AI."""

    __tablename__ = "generated_goals"
    __table_args__ = (
        Index("ix_generated_goals_company_id", "company_id"),
        Index("ix_generated_goals_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=True)

    goal_type: Mapped[str] = mapped_column(String(30), nullable=False)  # OKR, KPI, TEAM_GOAL, DEPARTMENT_GOAL, QUARTERLY_GOAL, WEEKLY_GOAL, DAILY_TASK
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="INDIVIDUAL")  # INDIVIDUAL, TEAM, DEPARTMENT, COMPANY
    
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    target_metric: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "100%", "500000 Revenue", "10 completed tickets"
    current_value: Mapped[str] = mapped_column(String(100), nullable=False, default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"))  # ACTIVE, ADJUSTED, ACHIEVED, MISSED

    original_target: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adjustment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    company: Mapped[Company] = relationship("Company", lazy="select")
    employee: Mapped[Employee | None] = relationship("Employee", lazy="select")
