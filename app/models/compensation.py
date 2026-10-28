"""Database models for AI Compensation recommendation engine.

Includes market salary benchmarks and detailed package recommendations logs.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, BigInteger, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text
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


# ---------------------------------------------------------------------------
# Batch 6: tenant-owned compensation bands and pay-equity analytics
# ---------------------------------------------------------------------------
from app.models.enterprise_common import EnterpriseModelMixin


class CompensationBand(EnterpriseModelMixin, Base):
    __tablename__ = "compensation_bands"
    __table_args__ = (
        UniqueConstraint("company_id", "band_code", name="uq_compensation_band_company_code"),
        Index("ix_compensation_bands_company_grade", "company_id", "grade"),
    )

    band_code: Mapped[str] = mapped_column(String(40), nullable=False)
    grade: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    min_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mid_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR", server_default=text("'INR'"))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class EmployeeCompensationBand(EnterpriseModelMixin, Base):
    __tablename__ = "employee_compensation_bands"
    __table_args__ = (
        Index("ix_employee_comp_bands_employee_current", "employee_id", "is_current"),
        Index("ix_employee_comp_bands_company_band", "company_id", "band_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    band_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("compensation_bands.id", ondelete="RESTRICT"), nullable=False)
    annual_salary_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CompensationMarketBenchmark(EnterpriseModelMixin, Base):
    __tablename__ = "compensation_market_benchmarks"
    __table_args__ = (
        UniqueConstraint("company_id", "grade", "designation", "region", name="uq_comp_market_grade_role_region"),
    )

    grade: Mapped[str] = mapped_column(String(40), nullable=False)
    designation: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False, default="IN", server_default=text("'IN'"))
    min_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    median_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(150), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)


class DepartmentIncrementBudget(EnterpriseModelMixin, Base):
    __tablename__ = "department_increment_budgets"
    __table_args__ = (
        UniqueConstraint("company_id", "department", "fiscal_year", name="uq_increment_budget_department_year"),
    )

    department: Mapped[str] = mapped_column(String(100), nullable=False)
    fiscal_year: Mapped[str] = mapped_column(String(9), nullable=False)
    budget_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    modeled_increment_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    scenario_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
