"""SQLAlchemy models for HRMS Core Modules.

Includes:
- AttendanceRegularizationRequest
- AnalyticsSnapshot
- CompanySettingsExtended
- EmploymentType
- Holiday
- PerformanceKPI
- ComplianceRecord
- EmployeeHealthRecord
- AIInteraction
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.user import User


class AttendanceRegularizationRequest(Base):
    """Employee attendance regularization / correction request with approval workflow."""

    __tablename__ = "attendance_regularization_requests"
    __table_args__ = (
        Index("ix_att_reg_emp_id", "employee_id"),
        Index("ix_att_reg_company_id", "company_id"),
        Index("ix_att_reg_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attendance_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendances.id", ondelete="SET NULL"), nullable=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    request_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AnalyticsSnapshot(Base):
    """Pre-computed analytics metric snapshots for fast dashboard reporting."""

    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        Index("ix_analytics_snapshots_key_date", "metric_key", "period_date"),
        Index("ix_analytics_snapshots_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False, default="daily", server_default=text("'daily'"))
    period_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmploymentType(Base):
    """Master record for employment types (Full-Time, Contract, Intern, etc.)."""

    __tablename__ = "employment_types"
    __table_args__ = (
        Index("ix_employment_types_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Holiday(Base):
    """Company public and optional holiday calendar."""

    __tablename__ = "holidays"
    __table_args__ = (
        Index("ix_holidays_company_date", "company_id", "holiday_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="national", server_default=text("'national'"))
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PerformanceKPI(Base):
    """Key Performance Indicator tied to individual employee goals or reviews."""

    __tablename__ = "performance_kpis"
    __table_args__ = (
        Index("ix_performance_kpis_goal_id", "goal_id"),
        Index("ix_performance_kpis_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee_performance_goals.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    weightage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.0"))
    target_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("100.0"))
    actual_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.0"))
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="%", server_default=text("'%'"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_PROGRESS", server_default=text("'IN_PROGRESS'"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ComplianceRecord(Base):
    """Compliance obligations, statutory filings, and POSH policy acknowledgements."""

    __tablename__ = "compliance_records"
    __table_args__ = (
        Index("ix_compliance_records_company_id", "company_id"),
        Index("ix_compliance_records_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=True
    )
    compliance_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="compliant", server_default=text("'compliant'"))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EmployeeHealthRecord(Base):
    """Employee clinical profile, checkup logs, and fitness clearances (sensitive)."""

    __tablename__ = "employee_health_records"
    __table_args__ = (
        Index("ix_emp_health_emp_id", "employee_id"),
        Index("ix_emp_health_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(50), nullable=False, default="medical_checkup")
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    fitness_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    encrypted_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checkup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    doctor_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AIInteraction(Base):
    """Audit and conversation log across all HR AI Assistant interactions."""

    __tablename__ = "ai_interactions"
    __table_args__ = (
        Index("ix_ai_interactions_module_user", "module", "user_id"),
        Index("ix_ai_interactions_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False, default="gemini-1.5-pro", server_default=text("'gemini-1.5-pro'"))
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
