"""Database models for AI Compensation recommendation engine.

Includes market salary benchmarks and detailed package recommendations logs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee


class MarketCompensationBenchmark(Base):
    """Annualized base pay market benchmarks sorted by designations and job seniority."""

    __tablename__ = "market_compensation_benchmarks"
    __table_args__ = (
        Index("ix_benchmarks_designation_exp", "designation", "experience_years"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, nullable=False)

    market_min_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    market_median_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    market_max_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    
    region: Mapped[str] = mapped_column(String(100), nullable=False, default="Global")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AICompensationRecommendation(Base):
    """Personalized AI compensation audit recommended for individual staff members."""

    __tablename__ = "ai_compensation_recommendations"
    __table_args__ = (
        Index("ix_compensation_recs_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    recommended_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    recommended_bonus: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    recommended_incentives: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    recommended_retention_bonus: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    recommended_stock_options: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recommend_promotion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recommended_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recommended_increment_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))

    market_ratio: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=Decimal("1.00"))  # current salary / market median
    equity_status: Mapped[str] = mapped_column(String(50), nullable=False, default="COMPLIANT")  # COMPLIANT, UNDERPAID, OVERPAID
    
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
