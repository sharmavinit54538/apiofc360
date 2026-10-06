"""SQLAlchemy models for Payroll Module (v1 & v2).

Includes:
- PayrollPeriod: Pay cycles/periods definition
- PayrollRunEmployee: Employee-level calculations and validation for a payroll run
- PayComponent: Earnings, deductions, statutory, employer contributions
- Compensation: Current employee CTC structure in paise
- CompensationRevision: CTC revision requests with approval workflow
- VariableInput: Variable pay (overtime, bonus, incentives, reimbursements, LOP)
- PaymentBatch: Payment batches for disbursement
- PaymentBatchItem: Line items per employee in a payment batch
- PaymentBatchBankFile: Bank advice export files (HDFC, ICICI, SBI, Generic NEFT)
- FullAndFinalSettlement: F&F settlement records and approval workflow
- ProvisionSlip: Provision payslips for review
- CompanyBankAccount: Organization bank accounts for salary payouts
- PayrollReportExport: Async report generation tracker
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    JSON,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.payroll import PayrollRun
    from app.models.user import User


class PayrollPeriod(Base):
    """Payroll Period defining calendar boundaries and pay dates for a company."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        Index("ix_payroll_periods_company_id", "company_id"),
        Index("ix_payroll_periods_dates", "start_date", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="OPEN", server_default=text("'OPEN'")
    )  # OPEN | PROCESSING | CLOSED | VOID
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    runs: Mapped[list["PayrollRun"]] = relationship(
        "PayrollRun", back_populates="period", cascade="all, delete-orphan", lazy="select"
    )
    variable_inputs: Mapped[list["VariableInput"]] = relationship(
        "VariableInput", back_populates="period", cascade="all, delete-orphan", lazy="select"
    )


class PayrollRunEmployee(Base):
    """Employee-level calculation summary and validation issues for a Payroll Run."""

    __tablename__ = "payroll_run_employees"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_id", name="uq_run_employee"),
        Index("ix_run_employees_run_id", "run_id"),
        Index("ix_run_employees_employee_id", "employee_id"),
        Index("ix_run_employees_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    gross_earnings_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    total_deductions_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    net_pay_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    paid_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("30.0"), server_default=text("30.0")
    )
    lop_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0.0"), server_default=text("0.0")
    )

    validation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="VALID", server_default=text("'VALID'")
    )  # VALID | WARNING | ERROR
    validation_messages: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )  # PENDING | PROCESSED | HELD | EXCLUDED

    earnings_breakup: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deductions_breakup: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    run: Mapped["PayrollRun"] = relationship(
        "PayrollRun", back_populates="run_employees", lazy="select"
    )
    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class PayComponent(Base):
    """Company-wide Pay Component catalog (Earnings, Deductions, Statutory)."""

    __tablename__ = "pay_components"
    __table_args__ = (
        Index("ix_pay_components_company_id", "company_id"),
        Index("ix_pay_components_code", "code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # earning | deduction | employer_contribution
    taxable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    statutory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    calculation_method: Mapped[str] = mapped_column(
        String(30), nullable=False, default="flat", server_default=text("'flat'")
    )  # flat | percentage_of_basic | percentage_of_ctc | formula
    default_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    formula_expr: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Compensation(Base):
    """Employee's active annual compensation in integer paise."""

    __tablename__ = "compensations"
    __table_args__ = (
        Index("ix_compensations_employee_id", "employee_id"),
        Index("ix_compensations_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    ctc_annual_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    basic_monthly_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    hra_monthly_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    special_allowance_monthly_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    effective_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )  # ACTIVE | SUPERSEDED | INACTIVE
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class CompensationRevision(Base):
    """Pending or finalized salary revision requests with approval workflow."""

    __tablename__ = "compensation_revisions"
    __table_args__ = (
        Index("ix_comp_revisions_employee_id", "employee_id"),
        Index("ix_comp_revisions_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    current_ctc_annual_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    new_ctc_annual_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )  # PENDING | APPROVED | REJECTED

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class VariableInput(Base):
    """Variable pay inputs (overtime, bonuses, reimbursements, deductions, LOP)."""

    __tablename__ = "variable_inputs"
    __table_args__ = (
        Index("ix_variable_inputs_employee_id", "employee_id"),
        Index("ix_variable_inputs_period_id", "period_id"),
        Index("ix_variable_inputs_company_id", "company_id"),
        Index("ix_variable_inputs_type", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_periods.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # overtime | bonus | incentive | commission | reimbursement | deduction | advance_recovery | lop | other
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    units: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    rate_per_unit_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )  # PENDING | APPROVED | REJECTED

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")
    period: Mapped["PayrollPeriod"] = relationship("PayrollPeriod", back_populates="variable_inputs", lazy="select")


class PaymentBatch(Base):
    """Payment disbursement batch created from a finalized payroll run."""

    __tablename__ = "payment_batches"
    __table_args__ = (
        Index("ix_payment_batches_company_id", "company_id"),
        Index("ix_payment_batches_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    batch_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    source_account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payment_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NEFT", server_default=text("'NEFT'")
    )  # NEFT | RTGS | IMPS | UPI

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'")
    )  # DRAFT | VALIDATED | APPROVED | SUBMITTED | RECONCILED | REJECTED

    total_amount_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    total_records: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    bank_reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)

    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    items: Mapped[list["PaymentBatchItem"]] = relationship(
        "PaymentBatchItem", back_populates="batch", cascade="all, delete-orphan", lazy="select"
    )
    bank_files: Mapped[list["PaymentBatchBankFile"]] = relationship(
        "PaymentBatchBankFile", back_populates="batch", cascade="all, delete-orphan", lazy="select"
    )
    run: Mapped["PayrollRun"] = relationship("PayrollRun", lazy="select")


class PaymentBatchItem(Base):
    """Disbursement line item per employee in a payment batch."""

    __tablename__ = "payment_batch_items"
    __table_args__ = (
        Index("ix_payment_batch_items_batch_id", "batch_id"),
        Index("ix_payment_batch_items_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payment_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )  # PENDING | HELD | RELEASED | SUCCESS | FAILED | RETRIED

    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    batch: Mapped["PaymentBatch"] = relationship(
        "PaymentBatch", back_populates="items", lazy="select"
    )
    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class PaymentBatchBankFile(Base):
    """Bank file format export generated for a payment batch."""

    __tablename__ = "payment_batch_bank_files"
    __table_args__ = (
        Index("ix_batch_bank_files_batch_id", "batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payment_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    file_format: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # HDFC_CSV | ICICI_EXCEL | SBI_TXT | GENERIC_NEFT_CSV
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="GENERATED", server_default=text("'GENERATED'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    batch: Mapped["PaymentBatch"] = relationship(
        "PaymentBatch", back_populates="bank_files", lazy="select"
    )


class FullAndFinalSettlement(Base):
    """Full & Final Settlement for exiting employees."""

    __tablename__ = "full_and_final_settlements"
    __table_args__ = (
        Index("ix_fnf_settlements_employee_id", "employee_id"),
        Index("ix_fnf_settlements_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    resignation_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_working_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # resignation | termination | retirement | layoff | contract_end
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    notice_period_days_required: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    notice_period_days_served: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    shortfall_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="DRAFT", server_default=text("'DRAFT'")
    )  # DRAFT | PENDING_APPROVAL | APPROVED | FINALIZED | REJECTED

    net_payable_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    settlement_breakup: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statement_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    finalized_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")


class ProvisionSlip(Base):
    """Provisional payslip estimate generated before run finalization."""

    __tablename__ = "provision_slips"
    __table_args__ = (
        Index("ix_provision_slips_employee_id", "employee_id"),
        Index("ix_provision_slips_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payroll_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    slip_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)

    gross_earnings_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    total_deductions_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    net_pay_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )

    breakup: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="GENERATED", server_default=text("'GENERATED'")
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    employee: Mapped["Employee"] = relationship("Employee", lazy="select")
    run: Mapped["PayrollRun | None"] = relationship("PayrollRun", lazy="select")


class CompanyBankAccount(Base):
    """Company operational bank account for salary disbursals and taxes."""

    __tablename__ = "company_bank_accounts"
    __table_args__ = (
        Index("ix_company_bank_accounts_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    ifsc_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_holder_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="CURRENT", server_default=text("'CURRENT'")
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    company: Mapped["Company"] = relationship("Company", lazy="select")


class PayrollReportExport(Base):
    """Async report exports tracker for downloading CSV/XLSX reports."""

    __tablename__ = "payroll_report_exports"
    __table_args__ = (
        Index("ix_payroll_report_exports_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    report_key: Mapped[str] = mapped_column(String(100), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False, default="csv", server_default=text("'csv'"))
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default=text("'PENDING'")
    )  # PENDING | PROCESSING | COMPLETED | FAILED
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
