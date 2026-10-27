"""Full & Final Settlement (FNF) and Gratuity calculation service."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.exit import EmployeeExit, FnfSettlement
from app.models.payroll import (
    AdvanceLoan,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)

logger = logging.getLogger(__name__)


class FnfCalculationService:
    """Calculates statutory gratuity, leave encashment, pending salary, and recoveries for employee exit."""

    #: `Employee.employment_type` values that qualify for pro-rata gratuity
    #: without the 5-year minimum tenure (fixed-term contract employees).
    FIXED_TERM_EMPLOYMENT_TYPES = frozenset({"FIXED_TERM", "FIXED_TERM_CONTRACT", "CONTRACT"})

    def __init__(self, db: AsyncSession):
        self.db = db

    @classmethod
    def is_fixed_term(cls, employment_type: Optional[str]) -> bool:
        """Whether the employee is engaged on a fixed-term contract."""
        if not employment_type:
            return False
        return str(employment_type).strip().upper() in cls.FIXED_TERM_EMPLOYMENT_TYPES

    @classmethod
    def enforce_settlement_maker_checker(
        cls,
        session: AsyncSession,
        *,
        settlement,
        approver_id,
        actor_role: Optional[str] = None,
        action: str = "APPROVE",
    ):
        """Strict maker-checker guard for Full & Final settlements.

        Delegates to the shared payroll permission helper so a
        ``FullAndFinalSettlement`` can never be approved by the user who created or
        processed it.  Raises ``ForbiddenException`` (HTTP 403) with error code
        ``MAKER_CHECKER_VIOLATION`` and writes an immutable ``PayrollAuditService``
        record when the tenant's
        ``StatutoryComplianceConfig.payroll_maker_checker_enforced`` is ``True``.
        """
        from app.api.payroll.permissions import enforce_maker_checker

        maker_ids = []
        for attr in ("created_by", "processed_by"):
            value = getattr(settlement, attr, None)
            if value is None:
                continue
            try:
                parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except (ValueError, AttributeError, TypeError):
                continue
            if parsed not in maker_ids:
                maker_ids.append(parsed)

        return enforce_maker_checker(
            session,
            entity_type="FullAndFinalSettlement",
            entity_id=settlement.id,
            company_id=settlement.company_id,
            maker_ids=maker_ids,
            approver_id=approver_id,
            actor_role=actor_role,
            action=action,
            before_status=getattr(settlement, "status", None),
        )

    @staticmethod
    def compute_gratuity(
        basic_monthly: Decimal,
        joining_date: Optional[date],
        last_working_date: Optional[date],
        min_years_required: int = 5,
        employment_type: Optional[str] = None,
        fixed_term_pro_rata: bool = True,
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

        # Fixed-term employees: under the Payment of Gratuity (Amendment) Act,
        # 2018 (carried forward by the Code on Wages, 2019) a fixed-term employee
        # earns gratuity on a pro-rata basis for the period actually served, with
        # NO five-year minimum tenure requirement.
        if FnfCalculationService.is_fixed_term(employment_type) and fixed_term_pro_rata:
            if years_raw <= 0 or basic_monthly <= 0:
                return Decimal("0.00")
            pro_rata = (
                (Decimal("15.0") / Decimal("26.0"))
                * basic_monthly
                * Decimal(str(years_raw))
            )
            return pro_rata.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if years_raw < min_years_required:
            return Decimal("0.00")

        completed_years = int(years_raw)
        fractional_months = (years_raw - completed_years) * 12
        if fractional_months >= 6:
            completed_years += 1

        gratuity = (Decimal("15.0") / Decimal("26.0")) * basic_monthly * Decimal(str(completed_years))
        return gratuity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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

        # 2. Compute Gratuity.
        # Fixed-term employees accrue pro-rata gratuity without the 5-year minimum
        # tenure when the tenant's statutory config enables it (Code on Wages).
        fixed_term_pro_rata = True
        company_id = getattr(emp, "company_id", None) or getattr(exit_obj, "company_id", None)
        if company_id is not None:
            cfg_stmt = select(StatutoryComplianceConfig).where(
                StatutoryComplianceConfig.company_id == company_id,
                StatutoryComplianceConfig.is_active == True,  # noqa: E712
            )
            cfg = (await self.db.execute(cfg_stmt)).scalar_one_or_none()
            if cfg is not None:
                fixed_term_pro_rata = bool(
                    getattr(cfg, "fixed_term_pro_rata_gratuity_enabled", True)
                )

        gratuity = self.compute_gratuity(
            basic_monthly=basic_monthly,
            joining_date=emp.joining_date,
            last_working_date=exit_obj.last_working_date,
            employment_type=getattr(emp, "employment_type", None),
            fixed_term_pro_rata=fixed_term_pro_rata,
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
