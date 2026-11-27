"""Service for Employee Payroll Dashboard and Sensitive Bank Details Access."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.payroll import EmployeeInvestmentDeclaration, Payslip, StatutoryComplianceConfig
from app.models.payroll_models import Compensation
from app.services.payroll.audit_service import PayrollAuditService
from app.services.payroll.payslip_service import PayslipService

logger = logging.getLogger(__name__)


def _format_inr(paise: int) -> str:
    rupees = paise / 100.0
    return f"₹{rupees:,.2f}"


def _mask_account_number(acc: Optional[str]) -> str:
    if not acc:
        return "Not configured"
    clean = str(acc).strip()
    if len(clean) <= 4:
        return clean
    return ("•" * min(8, len(clean) - 4)) + clean[-4:]


class EmployeePayrollService:
    """Employee portal dashboard and sensitive data reveal."""

    @classmethod
    async def get_dashboard(
        cls, session: AsyncSession, employee_id: uuid.UUID, company_id: Optional[uuid.UUID] = None
    ) -> dict[str, Any]:
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        if company_id is not None:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        if not emp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

        # Current active compensation (never invent synthetic salary defaults)
        comp_stmt = select(Compensation).where(
            Compensation.employee_id == employee_id, Compensation.status == "ACTIVE"
        )
        comp = (await session.execute(comp_stmt)).scalar_one_or_none()
        ctc_paise = int(comp.ctc_annual_paise) if comp and comp.ctc_annual_paise is not None else 0

        # Recent payslips scoped to this employee (and company if present)
        ps_stmt = select(Payslip).where(Payslip.employee_id == employee_id)
        if emp.company_id is not None:
            ps_stmt = ps_stmt.where(Payslip.company_id == emp.company_id)
        ps_stmt = ps_stmt.order_by(desc(Payslip.period_year), desc(Payslip.period_month)).limit(6)
        payslips = (await session.execute(ps_stmt)).scalars().all()
        recent = [
            {
                "id": str(p.id),
                "run_id": str(p.payroll_run_id),
                "runId": str(p.payroll_run_id),
                "payslip_number": p.payslip_number,
                "period": f"{p.period_month:02d}/{p.period_year}",
                "periodName": f"{p.period_month:02d}/{p.period_year}",
                "gross_earnings": float(p.gross_earnings or 0),
                "total_deductions": float(p.total_deductions or 0),
                "net_pay": float(p.net_pay or 0),
                "net_pay_paise": int(round(float(p.net_pay or 0) * 100)),
                "status": p.payment_status or "PENDING",
                "pdf_path": p.pdf_path,
            }
            for p in payslips
        ]
        latest_ps = payslips[0] if payslips else None
        latest_net = recent[0]["net_pay_paise"] if recent else 0

        latest_payslip_obj = None
        if latest_ps:
            gross_p = int(round(float(latest_ps.gross_earnings or 0) * 100))
            ded_p = int(round(float(latest_ps.total_deductions or 0) * 100))
            net_p = int(round(float(latest_ps.net_pay or 0) * 100))
            latest_payslip_obj = {
                "runId": str(latest_ps.payroll_run_id),
                "periodName": f"{latest_ps.period_month:02d}/{latest_ps.period_year}",
                "payDate": latest_ps.payment_date.isoformat() if latest_ps.payment_date else None,
                "grossFormatted": _format_inr(gross_p),
                "deductionsFormatted": _format_inr(ded_p),
                "netPayFormatted": _format_inr(net_p),
                "netPayPaise": net_p,
                "status": latest_ps.payment_status or "PENDING",
                "downloadUrl": f"/api/v2/payroll/my-payslips/{latest_ps.payroll_run_id}/download",
            }

        ytd = await PayslipService.get_ytd_summary(session, employee_id, company_id=emp.company_id)
        totals = ytd.get("totals") or {}
        ytd_gross_p = int(totals.get("gross_earnings_paise") or 0)
        ytd_ded_p = int(totals.get("total_deductions_paise") or 0)
        ytd_net_p = int(totals.get("net_pay_paise") or 0)
        ytd_pf_p = int(totals.get("employee_pf_paise") or 0)
        ytd_tds_p = int(totals.get("tds_paise") or 0)

        today = date.today()
        fy_start = today.year if today.month >= 4 else today.year - 1
        fy_label = f"{fy_start}-{fy_start + 1}"
        decl = (
            await session.execute(
                select(EmployeeInvestmentDeclaration).where(
                    EmployeeInvestmentDeclaration.employee_id == employee_id,
                    EmployeeInvestmentDeclaration.financial_year == fy_label,
                )
            )
        ).scalar_one_or_none()
        cfg = (
            await session.execute(
                select(StatutoryComplianceConfig).where(
                    StatutoryComplianceConfig.company_id == emp.company_id,
                    StatutoryComplianceConfig.is_active == True,  # noqa: E712
                )
            )
        ).scalars().first()
        regime = (
            (decl.tax_regime if decl and decl.tax_regime else None)
            or (cfg.default_tax_regime if cfg and cfg.default_tax_regime else None)
            or "NEW"
        ).upper()
        declared_ex_paise = 0
        if decl:
            declared_ex_paise = int(round((
                float(decl.section_80c or 0)
                + float(decl.section_80d or 0)
                + float(decl.section_80ccd1b_nps or 0)
                + float(decl.home_loan_interest_24b or 0)
                + float(decl.section_80g or 0)
                + float(decl.hra_claimed or 0)
                + float(decl.lta_claimed or 0)
                + float(decl.other_deductions or 0)
            ) * 100))

        bank_acc = (
            await session.execute(
                select(EmployeeBankAccount).where(
                    EmployeeBankAccount.employee_id == employee_id,
                    EmployeeBankAccount.is_primary == True,  # noqa: E712
                )
            )
        ).scalars().first()
        bank_name = (bank_acc.bank_name if bank_acc else None) or getattr(emp, "bank_name", None) or "Not configured"
        raw_acc_num = (bank_acc.account_number if bank_acc else None) or getattr(emp, "bank_account_number", None)
        ifsc = (bank_acc.ifsc_code if bank_acc else None) or getattr(emp, "bank_ifsc", None) or "—"
        holder = (bank_acc.account_holder_name if bank_acc else None) or f"{emp.first_name} {emp.last_name}".strip()

        return {
            "employee_id": str(employee_id),
            "employeeId": str(employee_id),
            "employeeCode": emp.employee_id or str(employee_id),
            "employeeName": f"{emp.first_name} {emp.last_name}".strip(),
            "department": emp.department or "General",
            "designation": emp.designation or "Employee",
            "current_ctc_annual_paise": ctc_paise,
            "latest_net_pay_paise": latest_net,
            "recent_payslips": recent,
            "pending_reimbursements_count": 0,
            "tax_regime": regime,
            "latestPayslip": latest_payslip_obj,
            "ytdSummary": {
                "financialYear": ytd.get("financial_year", fy_label),
                "totalGrossPaise": ytd_gross_p,
                "totalDeductionsPaise": ytd_ded_p,
                "totalNetPaise": ytd_net_p,
                "totalPfPaise": ytd_pf_p,
                "totalTdsPaise": ytd_tds_p,
                "grossFormatted": _format_inr(ytd_gross_p),
                "deductionsFormatted": _format_inr(ytd_ded_p),
                "netFormatted": _format_inr(ytd_net_p),
            },
            "taxOverview": {
                "taxRegime": "OLD" if regime == "OLD" else "NEW",
                "declaredExemptionsPaise": declared_ex_paise,
                "projectedAnnualTaxPaise": ytd_tds_p,
                "taxDeductedSoFarPaise": ytd_tds_p,
                "remainingTaxPaise": 0,
                "annualTaxFormatted": _format_inr(ytd_tds_p),
                "taxDeductedFormatted": _format_inr(ytd_tds_p),
            },
            "bankDetails": {
                "bankName": bank_name,
                "accountNumberMasked": _mask_account_number(raw_acc_num),
                "ifscCode": ifsc,
                "accountHolderName": holder,
            },
        }

    @classmethod
    async def reveal_bank_account(
        cls,
        session: AsyncSession,
        employee_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        if company_id is not None:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found.")

        # Log sensitive data access in audit logs
        await PayrollAuditService.log_event(
            session=session,
            entity_type="EmployeeBankAccount",
            entity_id=employee_id,
            action="REVEAL_BANK_ACCOUNT",
            company_id=company_id or emp.company_id,
            actor_id=user_id,
            actor_role=user_role,
            reason=reason,
            extra_data={"target_employee_id": str(employee_id), "reason": reason},
        )
        await session.commit()

        # Resolve unmasked bank account from EmployeeBankAccount or Employee (no hardcoded dummy numbers)
        bank_acc = (
            await session.execute(
                select(EmployeeBankAccount).where(
                    EmployeeBankAccount.employee_id == employee_id,
                    EmployeeBankAccount.is_primary == True,  # noqa: E712
                )
            )
        ).scalars().first()
        acc_num = (bank_acc.account_number if bank_acc else None) or getattr(emp, "bank_account_number", None) or ""
        ifsc = (bank_acc.ifsc_code if bank_acc else None) or getattr(emp, "bank_ifsc", None) or ""
        bank_name = (bank_acc.bank_name if bank_acc else None) or getattr(emp, "bank_name", None) or ""
        holder_name = (bank_acc.account_holder_name if bank_acc else None) or f"{emp.first_name} {emp.last_name}".strip()

        return {
            "employee_id": str(employee_id),
            "employeeId": str(employee_id),
            "bank_name": bank_name,
            "account_number": acc_num,
            "accountNumber": acc_num,
            "ifsc_code": ifsc,
            "ifscCode": ifsc,
            "account_holder_name": holder_name,
            "autoHideSeconds": 30,
        }
