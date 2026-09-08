"""Full & Final Settlement (FNF) and Gratuity calculation service."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.exit import EmployeeExit, FnfSettlement
from app.models.payroll import AdvanceLoan, Payslip, SalaryStructure

logger = logging.getLogger(__name__)


class FnfCalculationService:
    """Calculates statutory gratuity, leave encashment, pending salary, and recoveries for employee exit."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def compute_gratuity(
        basic_monthly: Decimal,
        joining_date: Optional[date],
        last_working_date: Optional[date],
        min_years_required: int = 5,
    ) -> Decimal:
        """Compute Gratuity per Payment of Gratuity Act 1972:
        Gratuity = (last_drawn_basic / 26) * 15 * completed_years_of_service.
        
        Eligible if employee has completed 5+ years (60+ months) of continuous service.
        If service in final year exceeds 6 months, it is rounded up to next full year.
        """
        if not joining_date or not last_working_date or last_working_date <= joining_date:
            return Decimal("0.00")

        days_of_service = (last_working_date - joining_date).days
        years_raw = days_of_service / 365.25

        if years_raw < min_years_required:
            return Decimal("0.00")

        completed_years = int(years_raw)
        fractional_months = (years_raw - completed_years) * 12
        if fractional_months >= 6:
            completed_years += 1

        gratuity = (Decimal("15.0") / Decimal("26.0")) * basic_monthly * Decimal(str(completed_years))
        return gratuity.quantize(Decimal("0.01"))

    @staticmethod
    def compute_leave_encashment(
        unused_leave_days: Decimal,
        basic_monthly: Decimal,
    ) -> Decimal:
        """Compute leave encashment:
        Encashment = unused_leave_days * (basic_monthly / 30).
        """
        if unused_leave_days <= 0 or basic_monthly <= 0:
            return Decimal("0.00")
        encashment = unused_leave_days * (basic_monthly / Decimal("30.0"))
        return encashment.quantize(Decimal("0.01"))

    @staticmethod
    def compute_notice_recovery(
        required_notice_days: int,
        actual_notice_days: int,
        basic_monthly: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Compute notice shortfall recovery or surplus payout.
        
        Returns:
            (notice_recovery_deduction, notice_payout)
        """
        shortfall_days = max(0, required_notice_days - actual_notice_days)
        surplus_days = max(0, actual_notice_days - required_notice_days)
        per_day_salary = basic_monthly / Decimal("30.0")

        recovery = (Decimal(str(shortfall_days)) * per_day_salary).quantize(Decimal("0.01"))
        payout = (Decimal(str(surplus_days)) * per_day_salary).quantize(Decimal("0.01"))
        return recovery, payout

    async def calculate_fnf_preview(self, exit_id: uuid.UUID) -> dict:
        """Calculate complete FNF settlement numbers for an employee exit request."""
        exit_stmt = (
            select(EmployeeExit)
            .where(EmployeeExit.id == exit_id)
            .options(selectinload(EmployeeExit.employee))
        )
        exit_res = await self.db.execute(exit_stmt)
        exit_obj = exit_res.scalar_one_or_none()
        if not exit_obj:
            raise ValueError("Exit request not found.")

        emp = exit_obj.employee
        if not emp:
            raise ValueError("Employee not found for exit request.")

        # 1. Fetch Salary Structure
        sal_stmt = (
            select(SalaryStructure)
            .where(
                SalaryStructure.employee_id == emp.id,
                SalaryStructure.is_active == True,  # noqa: E712
            )
            .order_by(SalaryStructure.effective_from.desc())
        )
        sal_struct = (await self.db.execute(sal_stmt)).scalar_one_or_none()
        basic_monthly = sal_struct.basic_monthly if sal_struct else (Decimal(str(emp.basic_salary or "0.00")))
        hra_monthly = sal_struct.hra_monthly if sal_struct else (Decimal(str(emp.hra or "0.00")))
        gross_monthly = (
            sal_struct.basic_monthly + sal_struct.hra_monthly + sal_struct.conveyance_monthly + sal_struct.special_allowance_monthly
            if sal_struct else basic_monthly + hra_monthly
        )

        # 2. Compute Gratuity
        gratuity = self.compute_gratuity(
            basic_monthly=basic_monthly,
            joining_date=emp.joining_date,
            last_working_date=exit_obj.last_working_date,
        )

        # 3. Compute Unused Leave Balance & Leave Encashment
        leave_stmt = select(EmployeeLeavePolicy).where(EmployeeLeavePolicy.employee_id == emp.id)
        leave_policies = (await self.db.execute(leave_stmt)).scalars().all()
        unused_leave_days = sum(
            max(Decimal("0.0"), Decimal(str(p.total_days)) - Decimal(str(p.used_days)))
            for p in leave_policies
        )
        leave_encashment = self.compute_leave_encashment(unused_leave_days, basic_monthly)

        # 4. Notice Period Shortfall Recovery
        required_notice_days = getattr(emp, "notice_period_days", 30) or 30
        resignation_date = exit_obj.created_at.date() if hasattr(exit_obj.created_at, "date") else date.today()
        actual_notice_days = max(0, (exit_obj.last_working_date - resignation_date).days)
        notice_recovery, notice_payout = self.compute_notice_recovery(
            required_notice_days=required_notice_days,
            actual_notice_days=actual_notice_days,
            basic_monthly=basic_monthly,
        )

        # 5. Pending Active Loans Recovery
        loan_stmt = select(AdvanceLoan).where(
            AdvanceLoan.employee_id == emp.id,
            AdvanceLoan.status == "ACTIVE",
        )
        loans = (await self.db.execute(loan_stmt)).scalars().all()
        loan_recovery = sum(Decimal(str(l.outstanding_balance)) for l in loans)

        # 6. Pending Salary for Final Working Month (Prorated)
        last_day = exit_obj.last_working_date.day
        total_days_in_final_month = 30
        pending_salary = (basic_monthly * Decimal(str(last_day)) / Decimal(str(total_days_in_final_month))).quantize(Decimal("0.01"))

        # Calculate Total Earnings and Total Deductions
        total_earnings = (pending_salary + leave_encashment + gratuity + notice_payout).quantize(Decimal("0.01"))
        total_deductions = (notice_recovery + loan_recovery).quantize(Decimal("0.01"))
        net_payable = (total_earnings - total_deductions).quantize(Decimal("0.01"))

        tenure_years = round((exit_obj.last_working_date - emp.joining_date).days / 365.25, 1) if emp.joining_date else 0.0

        return {
            "exit_id": str(exit_id),
            "employee_id": str(emp.id),
            "employee_name": f"{emp.first_name} {emp.last_name}",
            "joining_date": emp.joining_date.isoformat() if emp.joining_date else None,
            "last_working_date": exit_obj.last_working_date.isoformat(),
            "tenure_years": tenure_years,
            "basic_monthly": float(basic_monthly),
            "last_salary": float(gross_monthly),
            "pending_salary": float(pending_salary),
            "leave_encashment": float(leave_encashment),
            "unused_leave_days": float(unused_leave_days),
            "gratuity": float(gratuity),
            "bonus": float(notice_payout),
            "incentives": 0.0,
            "recoveries": 0.0,
            "notice_recovery": float(notice_recovery),
            "required_notice_days": required_notice_days,
            "actual_notice_days": actual_notice_days,
            "asset_recovery": 0.0,
            "loan_recovery": float(loan_recovery),
            "other_deductions": 0.0,
            "total_earnings": float(total_earnings),
            "total_deductions": float(total_deductions),
            "net_payable_amount": float(net_payable),
            "payment_status": "PENDING",
        }
