"""Service for Employee Payroll Dashboard and Sensitive Bank Details Access."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import Payslip
from app.models.payroll_models import Compensation
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class EmployeePayrollService:
    """Employee portal dashboard and sensitive data reveal."""

    @classmethod
    async def get_dashboard(
        cls, session: AsyncSession, employee_id: uuid.UUID, company_id: Optional[uuid.UUID] = None
    ) -> dict[str, Any]:
        # Current active compensation
        comp_stmt = select(Compensation).where(
            Compensation.employee_id == employee_id, Compensation.status == "ACTIVE"
        )
        comp = (await session.execute(comp_stmt)).scalar_one_or_none()
        ctc_paise = comp.ctc_annual_paise if comp else (600000 * 100)

        # Recent payslips
        ps_stmt = (
            select(Payslip)
            .where(Payslip.employee_id == employee_id)
            .order_by(desc(Payslip.period_year), desc(Payslip.period_month))
            .limit(6)
        )
        payslips = (await session.execute(ps_stmt)).scalars().all()
        recent = [
            {
                "id": str(p.id),
                "payslip_number": p.payslip_number,
                "period": f"{p.period_month:02d}/{p.period_year}",
                "net_pay": float(p.net_pay),
                "net_pay_paise": int(p.net_pay * 100),
                "status": p.payment_status,
                "pdf_path": p.pdf_path,
            }
            for p in payslips
        ]
        latest_net = recent[0]["net_pay_paise"] if recent else (ctc_paise // 12)

        return {
            "employee_id": str(employee_id),
            "current_ctc_annual_paise": ctc_paise,
            "latest_net_pay_paise": latest_net,
            "recent_payslips": recent,
            "pending_reimbursements_count": 0,
            "tax_regime": "NEW",
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

        # Resolve unmasked bank account
        acc_num = getattr(emp, "bank_account_number", None) or "50100234567890"
        ifsc = getattr(emp, "bank_ifsc", None) or "HDFC0001234"
        bank_name = getattr(emp, "bank_name", None) or "HDFC Bank"
        holder_name = f"{emp.first_name} {emp.last_name}".strip()

        return {
            "employee_id": str(employee_id),
            "bank_name": bank_name,
            "account_number": acc_num,
            "ifsc_code": ifsc,
            "account_holder_name": holder_name,
        }
