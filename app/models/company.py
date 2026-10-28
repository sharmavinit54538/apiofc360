"""Company / Tenant database model."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import String, Date, DateTime, ForeignKey, Text, UniqueConstraint, func, Boolean, Integer, JSON, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee


class Company(Base):
    """Company / Tenant in the Multi-Tenant SaaS platform."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    onboarding_step: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    company_profile: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    hr_settings: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
    )
    office_latitude: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    office_longitude: Mapped[float | None] = mapped_column(
        nullable=True,
    )
    geofence_radius_meters: Mapped[float | None] = mapped_column(
        nullable=True,
        default=200.0,
    )
    timezone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default="Asia/Kolkata",
        server_default=text("'Asia/Kolkata'"),
    )
    currency: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        default="INR",
        server_default=text("'INR'"),
    )


class LegalEntity(TenantMixin, TimestampMixin, Base):
    """A real registered legal entity belonging to a tenant."""

    __tablename__ = "legal_entities"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_legal_entities_company_code"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pf_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    esi_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pt_reg_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lwf_reg_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    branches: Mapped[list[Branch]] = relationship("Branch", back_populates="legal_entity", lazy="select")
    manager: Mapped[Employee | None] = relationship("Employee", foreign_keys=[manager_id], lazy="select")


class Branch(TenantMixin, TimestampMixin, Base):
    """A physical branch with optional statutory registration overrides."""

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_branches_company_code"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    branch_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pf_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    esi_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pt_reg_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lwf_reg_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    legal_entity: Mapped[LegalEntity] = relationship("LegalEntity", back_populates="branches", lazy="select")
    branch_manager: Mapped[Employee | None] = relationship(
        "Employee", foreign_keys=[branch_manager_id], lazy="select"
    )



class EntityPayrollCalendar(TenantMixin, TimestampMixin, Base):
    """Entity-owned monthly payroll dates, independent of other tenant entities."""

    __tablename__ = "entity_payroll_calendars"
    __table_args__ = (
        UniqueConstraint("legal_entity_id", "period_month", "period_year", name="uq_entity_payroll_calendar_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="CASCADE"), nullable=False
    )
    payroll_period_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True
    )
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    processing_date: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    attendance_cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default=text("'OPEN'"))


class EmployeeEntityTransfer(TenantMixin, TimestampMixin, Base):
    """Auditable inter-entity employee transfer with an effective-dated transition."""

    __tablename__ = "employee_entity_transfers"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    from_legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="SET NULL", name="fk_entity_transfer_from_legal_entity"), nullable=True
    )
    to_legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entities.id", ondelete="RESTRICT"), nullable=False
    )
    from_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    to_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SCHEDULED", server_default=text("'SCHEDULED'"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
