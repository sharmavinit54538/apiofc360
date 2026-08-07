"""Database models for HR Analytics and Predictive Engine.

Includes analytics snapshots, attrition risk predictions, and forecasting runs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text, JSON
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee


class HRAnalyticsSnapshot(Base):
    """Stores compiled demographic, salary parity, leave, and attendance dashboards."""

    __tablename__ = "hr_analytics_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today, server_default=text("CURRENT_DATE"))

    total_headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_tenure_months: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0.0)
    overall_attrition_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0.0)

    diversity_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # gender, age distribution
    salary_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # budget, averages, gaps
    leave_attendance_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # unplanned leave ratios, avg work hours
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HRAttritionRiskPrediction(Base):
    """Stores AI predicted attrition risk details for employees."""

    __tablename__ = "hr_attrition_predictions"
    __table_args__ = (
        Index("ix_hr_attrition_predictions_employee", "employee_id"),
        Index("ix_hr_attrition_predictions_level", "risk_level"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    risk_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0.0)  # 0.000 to 1.000
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)  # LOW, MEDIUM, HIGH
    top_risk_factors: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ["Below benchmark pay", "High overtime hours"]
    retention_recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)

    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")


class HRForecastingRun(Base):
    """Logs quarterly or monthly projections for recruitment/budget."""

    __tablename__ = "hr_forecasting_runs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    forecast_type: Mapped[str] = mapped_column(String(50), nullable=False)  # HEADCOUNT, PAYROLL_EXPENSE, RECRUITMENT_NEEDS
    forecast_target_date: Mapped[date] = mapped_column(Date, nullable=False)

    predicted_value: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    lower_confidence_bound: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    upper_confidence_bound: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    model_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
