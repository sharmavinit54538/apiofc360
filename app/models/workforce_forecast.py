"""AI Workforce Forecasting model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal
from app.db.base import Base

class WorkforceForecastRun(Base):
    __tablename__ = "workforce_forecast_runs"
    __table_args__ = (Index("ix_workforce_forecast_company_id", "company_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    forecast_period: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "Q3 2026"
    predicted_hiring_needs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_attrition_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    future_skill_demand: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON
    salary_budget_estimate: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    workforce_plan_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    department_growth_forecast: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
