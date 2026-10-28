"""Tenant chart-of-accounts mappings, expenses, and GL reconciliation."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin


class GLAccountMapping(EnterpriseModelMixin, Base):
    __tablename__ = "gl_account_mappings"
    __table_args__ = (UniqueConstraint("company_id", "provider", "source_key", name="uq_gl_mapping_company_provider_key"),)

    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(String(60), nullable=False)
    account_code: Mapped[str] = mapped_column(String(60), nullable=False)
    account_name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class ExpensePosting(EnterpriseModelMixin, Base):
    __tablename__ = "expense_postings"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_expense_posting_idempotency"),
        Index("ix_expense_postings_company_status", "company_id", "status"),
    )

    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR", server_default=text("'INR'"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="POSTED", server_default=text("'POSTED'"))
    external_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)


class GLReconciliationReport(EnterpriseModelMixin, Base):
    __tablename__ = "gl_reconciliation_reports"
    __table_args__ = (Index("ix_gl_reconciliation_company_period", "company_id", "period_id"),)

    period_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    internal_total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    difference_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
