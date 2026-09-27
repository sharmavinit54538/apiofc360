"""Service for Payslip and Provision Slip generation, retrieval, and PDF downloads."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_models import PayrollRunEmployee, ProvisionSlip

logger = logging.getLogger(__name__)


class PayslipService:
    """Business logic for Payslips and Provision Slips."""

    @classmethod
    async def get_employee_payslips(
        cls, session: AsyncSession, employee_id: uuid.UUID, page: int = 1, limit: int = 20
    ) -> dict[str, Any]:
        stmt = select(Payslip).where(Payslip.employee_id == employee_id)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(Payslip.period_year), desc(Payslip.period_month)).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()

        return {"items": items, "total": total, "page": page, "limit": limit}

    @classmethod
    async def get_payslip_detail(
        cls, session: AsyncSession, run_id: uuid.UUID, employee_id: uuid.UUID
    ) -> dict[str, Any]:
        stmt = select(Payslip).where(
            Payslip.payroll_run_id == run_id, Payslip.employee_id == employee_id
        )
        ps = (await session.execute(stmt)).scalar_one_or_none()
        if not ps:
            raise HTTPException(status_code=404, detail="Payslip not found for this employee and run.")

        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Employee"

        return {
            "id": str(ps.id),
            "payslip_number": ps.payslip_number,
            "employee_id": str(ps.employee_id),
            "employee_name": emp_name,
            "period_month": ps.period_month,
            "period_year": ps.period_year,
            "paid_days": float(ps.paid_days),
            "lop_days": float(ps.lop_days),
            "gross_earnings": float(ps.gross_earnings),
            "total_deductions": float(ps.total_deductions),
            "net_pay": float(ps.net_pay),
            "gross_earnings_paise": int(ps.gross_earnings * 100),
            "total_deductions_paise": int(ps.total_deductions * 100),
            "net_pay_paise": int(ps.net_pay * 100),
            "payment_status": ps.payment_status,
            "pdf_path": ps.pdf_path,
            "created_at": ps.created_at,
        }

    @classmethod
    async def generate_batch_payslips(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        employee_ids: Optional[List[str]] = None,
        force: bool = False,
        format_type: str = "pdf",
    ) -> int:
        stmt = select(Payslip).where(Payslip.payroll_run_id == run_id)
        if employee_ids:
            emp_uuids = [uuid.UUID(e) for e in employee_ids]
            stmt = stmt.where(Payslip.employee_id.in_(emp_uuids))

        payslips = (await session.execute(stmt)).scalars().all()
        generated_count = 0
        for ps in payslips:
            if not ps.pdf_path or force:
                ps.pdf_path = f"uploads/payslips/{run_id}/{ps.employee_id}.pdf"
                ps.generated_at = datetime.now()
                generated_count += 1

        await session.commit()
        return generated_count

    @classmethod
    async def get_payslip_file(
        cls, session: AsyncSession, run_id: uuid.UUID, employee_id: uuid.UUID
    ) -> tuple[bytes, str]:
        detail = await cls.get_payslip_detail(session, run_id, employee_id)
        content = (
            f"OFC360 PAYSLIP\n"
            f"==============\n"
            f"Payslip No: {detail['payslip_number']}\n"
            f"Employee: {detail['employee_name']}\n"
            f"Period: {detail['period_month']:02d}/{detail['period_year']}\n"
            f"Paid Days: {detail['paid_days']} | LOP Days: {detail['lop_days']}\n"
            f"Gross Earnings: Rs. {detail['gross_earnings']:,.2f}\n"
            f"Total Deductions: Rs. {detail['total_deductions']:,.2f}\n"
            f"Net Pay: Rs. {detail['net_pay']:,.2f}\n"
            f"Status: {detail['payment_status']}\n"
            f"==============\n"
        )
        filename = f"Payslip_{detail['period_year']}_{detail['period_month']}_{detail['payslip_number']}.txt"
        return content.encode("utf-8"), filename

    @classmethod
    async def list_provision_slips(
        cls, session: AsyncSession, employee_id: uuid.UUID
    ) -> List[ProvisionSlip]:
        stmt = (
            select(ProvisionSlip)
            .where(ProvisionSlip.employee_id == employee_id)
            .order_by(desc(ProvisionSlip.period_year), desc(ProvisionSlip.period_month))
        )
        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    async def get_provision_slip_pdf(
        cls, session: AsyncSession, slip_id: uuid.UUID
    ) -> tuple[bytes, str]:
        stmt = select(ProvisionSlip).where(ProvisionSlip.id == slip_id)
        slip = (await session.execute(stmt)).scalar_one_or_none()
        if not slip:
            raise HTTPException(status_code=404, detail="Provision slip not found.")

        content = (
            f"PROVISION PAYSLIP (ESTIMATE)\n"
            f"============================\n"
            f"Slip No: {slip.slip_number}\n"
            f"Period: {slip.period_month:02d}/{slip.period_year}\n"
            f"Gross Earnings: Rs. {slip.gross_earnings_paise / 100.0:,.2f}\n"
            f"Total Deductions: Rs. {slip.total_deductions_paise / 100.0:,.2f}\n"
            f"Net Pay (Est): Rs. {slip.net_pay_paise / 100.0:,.2f}\n"
            f"============================\n"
        )
        filename = f"ProvisionSlip_{slip.slip_number}.txt"
        return content.encode("utf-8"), filename
