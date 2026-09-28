"""Service for Statutory Compliance configuration and reports."""

from __future__ import annotations

import csv
import io
import logging
import uuid
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import Payslip, StatutoryComplianceConfig
from app.models.payroll_models import PayrollPeriod

logger = logging.getLogger(__name__)


class StatutoryService:
    """Business logic for statutory config and government filing reports."""

    @classmethod
    async def get_config(
        cls, session: AsyncSession, company_id: Optional[uuid.UUID] = None
    ) -> StatutoryComplianceConfig:
        stmt = select(StatutoryComplianceConfig).where(StatutoryComplianceConfig.is_active == True)
        if company_id:
            stmt = stmt.where(
                or_(
                    StatutoryComplianceConfig.company_id == company_id,
                    StatutoryComplianceConfig.company_id.is_(None),
                )
            )
        cfg = (await session.execute(stmt)).scalar_one_or_none()
        if not cfg:
            cfg = StatutoryComplianceConfig(is_active=True)
            session.add(cfg)
            await session.commit()
            await session.refresh(cfg)
        return cfg

    @classmethod
    async def get_summary(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        component: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        # Query payslips for this period month/year
        ps_stmt = select(Payslip).where(
            Payslip.period_month == period.period_month,
            Payslip.period_year == period.period_year,
        )
        if company_id:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)
        payslips = (await session.execute(ps_stmt)).scalars().all()

        emp_contrib = 0
        empr_contrib = 0
        comp_name = (component or "PF").upper()

        for ps in payslips:
            if comp_name == "PF":
                emp_contrib += int(ps.employee_pf * 100)
                empr_contrib += int(ps.employer_pf * 100)
            elif comp_name == "ESI":
                emp_contrib += int(ps.employee_esi * 100)
                empr_contrib += int(ps.employer_esi * 100)
            elif comp_name == "PT":
                emp_contrib += int(ps.professional_tax * 100)
            elif comp_name == "TDS":
                emp_contrib += int(ps.tds * 100)

        total_liability = emp_contrib + empr_contrib

        return {
            "component": comp_name,
            "period_id": str(period_id),
            "total_employees": len(payslips),
            "employee_contribution_paise": emp_contrib,
            "employer_contribution_paise": empr_contrib,
            "total_liability_paise": total_liability,
            "breakup": [
                {
                    "employee_count": len(payslips),
                    "employee_total": emp_contrib / 100.0,
                    "employer_total": empr_contrib / 100.0,
                    "total": total_liability / 100.0,
                }
            ],
        }

    @classmethod
    async def generate_report_file(
        cls,
        session: AsyncSession,
        component: str,
        period_id: uuid.UUID,
        file_format: str = "csv",
    ) -> dict[str, Any]:
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        ps_stmt = (
            select(Payslip)
            .join(Employee, Payslip.employee_id == Employee.id)
            .where(
                Payslip.period_month == period.period_month,
                Payslip.period_year == period.period_year,
            )
        )
        payslips = (await session.execute(ps_stmt)).scalars().all()

        output = io.StringIO()
        comp = component.upper()

        if file_format == "txt" and comp == "PF":
            # EPFO Electronic Challan Return (ECR) text format:
            # UAN#~#MEMBER_NAME#~#GROSS_WAGES#~#EPF_WAGES#~#EPS_WAGES#~#EDLI_WAGES#~#EPF_CONTRI_REMITTED#~#EPS_CONTRI_REMITTED#~#EPF_EPS_DIFF_REMITTED#~#NCP_DAYS#~#REFUND_OF_ADVANCES
            for ps in payslips:
                emp_info = (
                    await session.execute(select(Employee).where(Employee.id == ps.employee_id))
                ).scalar_one_or_none()
                uan = getattr(emp_info, "pf_number", "") or "100000000000"
                name = f"{emp_info.first_name} {emp_info.last_name}".strip() if emp_info else "MEMBER"
                output.write(
                    f"{uan}#~#{name}#~#{ps.gross_earnings:.2f}#~#{ps.basic:.2f}#~#{ps.basic:.2f}#~#{ps.basic:.2f}#~#{ps.employee_pf:.2f}#~#{ps.employer_pf:.2f}#~#0.00#~#{ps.lop_days:.0f}#~#0\n"
                )
        else:
            writer = csv.writer(output)
            writer.writerow(["Employee ID", "Name", "Component", "Employee Share", "Employer Share", "Total"])
            for ps in payslips:
                emp_info = (
                    await session.execute(select(Employee).where(Employee.id == ps.employee_id))
                ).scalar_one_or_none()
                name = f"{emp_info.first_name} {emp_info.last_name}".strip() if emp_info else "Employee"
                emp_code = emp_info.employee_id if emp_info else str(ps.employee_id)
                emp_s = ps.employee_pf if comp == "PF" else ps.employee_esi
                empr_s = ps.employer_pf if comp == "PF" else ps.employer_esi
                writer.writerow([emp_code, name, comp, f"{emp_s:.2f}", f"{empr_s:.2f}", f"{(emp_s + empr_s):.2f}"])

        file_name = f"Statutory_{comp}_{period.period_year}_{period.period_month:02d}.{file_format}"
        return {
            "component": comp,
            "period_id": str(period_id),
            "file_name": file_name,
            "format": file_format,
            "total_records": len(payslips),
            "content": output.getvalue(),
        }
