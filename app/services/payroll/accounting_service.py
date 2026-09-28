"""Service for Accounting exports and Journal Voucher generation."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import Payslip
from app.models.payroll_models import PayrollPeriod

logger = logging.getLogger(__name__)


class AccountingService:
    """Generates double-entry general ledger journal entries for payroll periods."""

    @classmethod
    async def export_accounting_entries(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        ps_stmt = select(Payslip).where(
            Payslip.period_month == period.period_month,
            Payslip.period_year == period.period_year,
        )
        if company_id:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)
        payslips = (await session.execute(ps_stmt)).scalars().all()

        total_gross = sum(float(ps.gross_earnings) for ps in payslips)
        total_net = sum(float(ps.net_pay) for ps in payslips)
        total_pf_emp = sum(float(ps.employee_pf) for ps in payslips)
        total_pf_empr = sum(float(ps.employer_pf) for ps in payslips)
        total_esi_emp = sum(float(ps.employee_esi) for ps in payslips)
        total_esi_empr = sum(float(ps.employer_esi) for ps in payslips)
        total_pt = sum(float(ps.professional_tax) for ps in payslips)
        total_tds = sum(float(ps.tds) for ps in payslips)

        journal_entries = [
            # Debits (Expenses)
            {"account_code": "5001", "account_name": "Salaries & Wages Expense", "debit": round(total_gross, 2), "credit": 0.0},
            {"account_code": "5002", "account_name": "Employer PF Contribution", "debit": round(total_pf_empr, 2), "credit": 0.0},
            {"account_code": "5003", "account_name": "Employer ESI Contribution", "debit": round(total_esi_empr, 2), "credit": 0.0},
            # Credits (Liabilities)
            {"account_code": "2001", "account_name": "Net Salaries Payable", "debit": 0.0, "credit": round(total_net, 2)},
            {"account_code": "2002", "account_name": "PF Payable (Employee + Employer)", "debit": 0.0, "credit": round(total_pf_emp + total_pf_empr, 2)},
            {"account_code": "2003", "account_name": "ESI Payable (Employee + Employer)", "debit": 0.0, "credit": round(total_esi_emp + total_esi_empr, 2)},
            {"account_code": "2004", "account_name": "Professional Tax Payable", "debit": 0.0, "credit": round(total_pt, 2)},
            {"account_code": "2005", "account_name": "TDS on Salaries Payable", "debit": 0.0, "credit": round(total_tds, 2)},
        ]

        total_debits = sum(e["debit"] for e in journal_entries)
        total_credits = sum(e["credit"] for e in journal_entries)

        return {
            "period_id": str(period_id),
            "period_name": period.name,
            "period_month": period.period_month,
            "period_year": period.period_year,
            "currency": "INR",
            "is_balanced": abs(total_debits - total_credits) < 1.0,
            "total_debits": round(total_debits, 2),
            "total_credits": round(total_credits, 2),
            "entries": journal_entries,
        }
