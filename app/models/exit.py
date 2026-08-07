"""Exit Management database models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class EmployeeExit(Base):
    """Core employee exit/resignation record."""

    __tablename__ = "employee_exits"
    __table_args__ = (
        Index("ix_employee_exits_employee_id", "employee_id"),
        Index("ix_employee_exits_status", "status"),
        Index("ix_employee_exits_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    last_working_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    personal_email: Mapped[str] = mapped_column(String(255), nullable=False)
    personal_phone: Mapped[str] = mapped_column(String(20), nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SUBMITTED", server_default=text("'SUBMITTED'"))

    manager_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    hr_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit & Soft Delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    employee: Mapped[Employee] = relationship("Employee", foreign_keys=[employee_id], lazy="select")
    knowledge_transfers: Mapped[list[KnowledgeTransfer]] = relationship("KnowledgeTransfer", back_populates="exit_rel", cascade="all, delete-orphan", lazy="select")
    asset_returns: Mapped[list[AssetReturn]] = relationship("AssetReturn", back_populates="exit_rel", cascade="all, delete-orphan", lazy="select")
    clearances: Mapped[list[ClearanceRequest]] = relationship("ClearanceRequest", back_populates="exit_rel", cascade="all, delete-orphan", lazy="select")
    exit_interviews: Mapped[list[ExitInterview]] = relationship("ExitInterview", back_populates="exit_rel", cascade="all, delete-orphan", lazy="select")
    fnf_settlements: Mapped[list[FnfSettlement]] = relationship("FnfSettlement", back_populates="exit_rel", cascade="all, delete-orphan", lazy="select")
    documents: Mapped[list[ExitDocument]] = relationship("ExitDocument", back_populates="exit_rel", cascade="all, delete-orphan", lazy="select")


class KnowledgeTransfer(Base):
    """Knowledge Transfer handovers tracking."""

    __tablename__ = "knowledge_transfers"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False)

    projects_handed_over: Mapped[str] = mapped_column(Text, nullable=False)
    documentation_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    replacement_assigned_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)

    manager_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    exit_rel: Mapped[EmployeeExit] = relationship("EmployeeExit", back_populates="knowledge_transfers")
    replacement: Mapped[Employee | None] = relationship("Employee", foreign_keys=[replacement_assigned_id], lazy="select")


class AssetReturn(Base):
    """Company assets return checklists."""

    __tablename__ = "asset_returns"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False)

    asset_name: Mapped[str] = mapped_column(String(100), nullable=False)  # Laptop, Monitor, Mouse,SIM Card etc.
    return_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING/RETURNED
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    hr_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    exit_rel: Mapped[EmployeeExit] = relationship("EmployeeExit", back_populates="asset_returns")


class ClearanceRequest(Base):
    """No Dues Department Clearances."""

    __tablename__ = "clearance_requests"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False)

    it_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hr_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    finance_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    admin_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manager_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    security_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    overall_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING/CLEARED

    exit_rel: Mapped[EmployeeExit] = relationship("EmployeeExit", back_populates="clearances")


class ExitInterview(Base):
    """Exit Interview details."""

    __tablename__ = "exit_interviews"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False)

    interview_date: Mapped[date] = mapped_column(Date, nullable=False)
    interviewer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_for_leaving: Mapped[str] = mapped_column(Text, nullable=False)
    would_rejoin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suggestions: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    exit_rel: Mapped[EmployeeExit] = relationship("EmployeeExit", back_populates="exit_interviews")


class FnfSettlement(Base):
    """Full & Final Settlement details."""

    __tablename__ = "fnf_settlements"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False)

    # Earnings
    last_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    pending_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    leave_encashment: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    bonus: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    incentives: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)

    # Deductions/Recoveries
    recoveries: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    notice_recovery: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    asset_recovery: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    loan_recovery: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    other_deductions: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)

    net_payable_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0.0)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING/PAID
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    exit_rel: Mapped[EmployeeExit] = relationship("EmployeeExit", back_populates="fnf_settlements")


class ExitDocument(Base):
    """Generated Exit Documents (Relieving, Experience, Salary etc.)."""

    __tablename__ = "exit_documents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exit_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False)

    document_type: Mapped[str] = mapped_column(String(50), nullable=False)  # RELIEVING_LETTER, EXPERIENCE_LETTER etc.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    exit_rel: Mapped[EmployeeExit] = relationship("EmployeeExit", back_populates="documents")
