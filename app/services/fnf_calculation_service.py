"""Full & Final Settlement (FNF) and Gratuity calculation service."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import func, or_, select
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
        da_monthly: Decimal = Decimal("0.00"),
        gratuity_ceiling: Decimal = Decimal("2000000.00"),
    ) -> Decimal:
        """Compute Gratuity per Payment of Gratuity Act 1972:
        Gratuity = (last_drawn_basic / 26) * 15 * completed_years_of_service.
        
        Eligible if employee has completed 5+ years (60+ months) of continuous service.
        If service in final year exceeds 6 months, it is rounded up to next full year.
        """
        if not joining_date or not last_working_date or last_working_date <= joining_date:
            return Decimal("0.00")
        basic_da_monthly = Decimal(str(basic_monthly)) + Decimal(str(da_monthly or 0))
        ceiling = Decimal(str(gratuity_ceiling)) if gratuity_ceiling is not None else None

        days_of_service = (last_working_date - joining_date).days
        years_raw = days_of_service / 365.25

        # Fixed-term employees: under the Payment of Gratuity (Amendment) Act,
        # 2018 (carried forward by the Code on Wages, 2019) a fixed-term employee
        # earns gratuity on a pro-rata basis for the period actually served, with
        # NO five-year minimum tenure requirement.
        if FnfCalculationService.is_fixed_term(employment_type) and fixed_term_pro_rata:
            if years_raw <= 0 or basic_da_monthly <= 0:
                return Decimal("0.00")
            pro_rata = (
                (Decimal("15.0") / Decimal("26.0"))
                * basic_da_monthly
                * Decimal(str(years_raw))
            )
            if ceiling is not None:
                pro_rata = min(pro_rata, ceiling)
            return pro_rata.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if years_raw < min_years_required:
            return Decimal("0.00")

        completed_years = int(years_raw)
        fractional_months = (years_raw - completed_years) * 12
        if fractional_months >= 6:
            completed_years += 1

        gratuity = (Decimal("15.0") / Decimal("26.0")) * basic_da_monthly * Decimal(str(completed_years))
        if ceiling is not None:
            gratuity = min(gratuity, ceiling)
        return gratuity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def compute_leave_encashment(
        unused_leave_days: Decimal,
        basic_monthly: Decimal,
        basis: str = "BASIC",
        gross_monthly: Decimal | None = None,
        divisor: int = 30,
    ) -> Decimal:
        """Encash using selectable Basic/Gross and a 26/30-day divisor."""
        normalized_basis = str(basis or "BASIC").upper()
        if normalized_basis not in {"BASIC", "GROSS"}:
            raise ValueError("Leave encashment basis must be BASIC or GROSS.")
        if divisor not in {26, 30}:
            raise ValueError("Leave encashment divisor must be 26 or 30.")
        monthly = Decimal(str(gross_monthly if normalized_basis == "GROSS" and gross_monthly is not None else basic_monthly))
        if unused_leave_days <= 0 or monthly <= 0:
            return Decimal("0.00")
        encashment = Decimal(str(unused_leave_days)) * (monthly / Decimal(str(divisor)))
        return encashment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def compute_notice_recovery(
        required_notice_days: int,
        actual_notice_days: int,
        basic_monthly: Decimal,
        waived: bool = False,
        buyout: bool = False,
        divisor: int = 30,
    ) -> tuple[Decimal, Decimal]:
        """Compute notice recovery/payout; waiver clears only shortfall recovery.

        Buyout keeps the shortfall recovery (the employee buys out unserved
        notice), while the explicit ``buyout`` argument documents that choice.
        """
        shortfall_days = max(0, required_notice_days - actual_notice_days)
        surplus_days = max(0, actual_notice_days - required_notice_days)
        if divisor not in {26, 30}:
            raise ValueError("Notice divisor must be 26 or 30.")
        per_day_salary = basic_monthly / Decimal(str(divisor))

        recovery = Decimal("0.00") if waived else (Decimal(str(shortfall_days)) * per_day_salary).quantize(Decimal("0.01"))
        payout = (Decimal(str(surplus_days)) * per_day_salary).quantize(Decimal("0.01"))
        return recovery, payout

    async def calculate_fnf_preview(
        self,
        exit_id: uuid.UUID,
        *,
        leave_basis: str | None = None,
        leave_divisor: int | None = None,
        da_monthly: Decimal | None = None,
        notice_waived: bool | None = None,
        notice_buyout: bool | None = None,
        unpaid_salary: Decimal | None = None,
        arrears: Decimal | None = None,
        variable_bonus: Decimal | None = None,
    ) -> dict:
        """Calculate a complete, reproducible FnF breakup from real ledgers."""
        from app.models.leave_balance import LeaveBalance
        from app.models.payroll import PayrollAttendanceInput

        exit_obj = (await self.db.execute(
            select(EmployeeExit).where(EmployeeExit.id == exit_id).options(selectinload(EmployeeExit.employee))
        )).scalar_one_or_none()
        if not exit_obj or not exit_obj.employee:
            raise ValueError("Exit request or employee not found.")
        emp = exit_obj.employee
        sal_struct = (await self.db.execute(
            select(SalaryStructure).where(
                SalaryStructure.employee_id == emp.id, SalaryStructure.is_active == True,  # noqa: E712
            ).order_by(SalaryStructure.effective_from.desc())
        )).scalars().first()
        basic_monthly = Decimal(str(sal_struct.basic_monthly if sal_struct else (emp.basic_salary or 0)))
        hra_monthly = Decimal(str(sal_struct.hra_monthly if sal_struct else (emp.hra or 0)))
        allowances = (sal_struct.other_allowances or {}) if sal_struct else {}
        detected_da = Decimal("0.00")
        other_allowances_total = Decimal("0.00")
        for key, value in allowances.items():
            normalized_key = str(key).strip().lower().replace(" ", "_")
            if normalized_key in {"da", "dearness_allowance"}:
                detected_da += Decimal(str(value or 0))
            else:
                other_allowances_total += Decimal(str(value or 0))
        da = Decimal(str(da_monthly)) if da_monthly is not None else detected_da
        gross_monthly = (
            Decimal(str(sal_struct.basic_monthly + sal_struct.hra_monthly + sal_struct.conveyance_monthly + sal_struct.special_allowance_monthly))
            if sal_struct else basic_monthly + hra_monthly
        ) + other_allowances_total + da

        fixed_term_pro_rata = True
        company_id = emp.company_id or exit_obj.company_id
        if company_id is not None:
            cfg = (await self.db.execute(select(StatutoryComplianceConfig).where(
                StatutoryComplianceConfig.company_id == company_id,
                StatutoryComplianceConfig.is_active == True,  # noqa: E712
            ))).scalars().first()
            if cfg is not None:
                fixed_term_pro_rata = bool(getattr(cfg, "fixed_term_pro_rata_gratuity_enabled", True))
        gratuity = self.compute_gratuity(
            basic_monthly=basic_monthly, joining_date=emp.joining_date,
            last_working_date=exit_obj.last_working_date,
            employment_type=emp.employment_type, fixed_term_pro_rata=fixed_term_pro_rata,
            da_monthly=da, gratuity_ceiling=Decimal("2000000.00"),
        )

        leave_breakup: list[dict] = []
        fy_start = exit_obj.last_working_date.year if exit_obj.last_working_date.month >= 4 else exit_obj.last_working_date.year - 1
        balances = (await self.db.execute(select(LeaveBalance).where(
            LeaveBalance.employee_id == emp.id,
            or_(LeaveBalance.year.is_(None), LeaveBalance.year == fy_start),
        ))).scalars().all()
        if balances:
            for balance in balances:
                leave_name = balance.leave_type or ""
                inferred = any(token in leave_name.lower() for token in ("earned", "privilege")) or leave_name.strip().lower() == "el" or Decimal(str(balance.carried_forward_days or 0)) > 0
                if balance.encashable is False or (balance.encashable is None and not inferred):
                    continue
                days = balance.remaining_days
                if balance.encashable_days is not None:
                    days = min(days, Decimal(str(balance.encashable_days)))
                basis = (leave_basis or balance.encashment_base or "BASIC").upper()
                divisor = leave_divisor or balance.encashment_divisor or 30
                amount = self.compute_leave_encashment(days, basic_monthly, basis, gross_monthly, divisor)
                if days > 0:
                    leave_breakup.append({"leave_type": leave_name, "days": days, "basis": basis, "divisor": divisor, "amount": amount})
        else:
            # Compatibility for tenants not yet moved to the canonical balance ledger.
            leave_policies = (await self.db.execute(select(EmployeeLeavePolicy).where(
                EmployeeLeavePolicy.employee_id == emp.id
            ))).scalars().all()
            for policy in leave_policies:
                inferred = any(token in (policy.leave_type or "").lower() for token in ("earned", "privilege")) or (policy.leave_type or "").strip().lower() == "el" or policy.carry_forward
                if policy.encashable is False or (policy.encashable is None and not inferred):
                    continue
                days = max(Decimal("0"), Decimal(str(policy.total_days or 0)) - Decimal(str(policy.used_days or 0)))
                if policy.encashable_days is not None:
                    days = min(days, Decimal(str(policy.encashable_days)))
                basis = (leave_basis or policy.encashment_base or "BASIC").upper()
                divisor = leave_divisor or policy.encashment_divisor or 30
                amount = self.compute_leave_encashment(days, basic_monthly, basis, gross_monthly, divisor)
                if days > 0:
                    leave_breakup.append({"leave_type": policy.leave_type, "days": days, "basis": basis, "divisor": divisor, "amount": amount})
        unused_leave_days = sum((item["days"] for item in leave_breakup), Decimal("0.00"))
        leave_encashment = sum((item["amount"] for item in leave_breakup), Decimal("0.00")).quantize(Decimal("0.01"))

        required_notice_days = exit_obj.notice_period_days_required
        if required_notice_days is None:
            required_notice_days = getattr(emp, "notice_period_days", 30) or 30
        actual_notice_days = exit_obj.notice_period_days_served
        if actual_notice_days is None:
            resignation_date = exit_obj.created_at.date() if hasattr(exit_obj.created_at, "date") else date.today()
            actual_notice_days = max(0, (exit_obj.last_working_date - resignation_date).days)
        waived = exit_obj.notice_waived if notice_waived is None else notice_waived
        buyout = exit_obj.notice_buyout if notice_buyout is None else notice_buyout
        notice_recovery, notice_payout = self.compute_notice_recovery(
            required_notice_days=required_notice_days, actual_notice_days=actual_notice_days,
            basic_monthly=basic_monthly, waived=bool(waived), buyout=bool(buyout),
        )
        shortfall_days = max(0, required_notice_days - actual_notice_days)

        loans = (await self.db.execute(select(AdvanceLoan).where(
            AdvanceLoan.employee_id == emp.id, AdvanceLoan.status == "ACTIVE",
        ))).scalars().all()
        loan_recovery = sum((Decimal(str(loan.outstanding_balance or 0)) for loan in loans), Decimal("0.00"))
        attendance = (await self.db.execute(select(PayrollAttendanceInput).where(
            PayrollAttendanceInput.employee_id == emp.id,
            PayrollAttendanceInput.period_month == exit_obj.last_working_date.month,
            PayrollAttendanceInput.period_year == exit_obj.last_working_date.year,
        ))).scalar_one_or_none()
        if unpaid_salary is not None:
            base_pending_salary = Decimal(str(unpaid_salary))
        elif exit_obj.unpaid_salary_days is not None:
            unpaid_days = max(Decimal("0"), Decimal(str(exit_obj.unpaid_salary_days)))
            base_pending_salary = (gross_monthly * unpaid_days / Decimal("30")).quantize(Decimal("0.01"))
        else:
            base_pending_salary = (gross_monthly * Decimal(str(exit_obj.last_working_date.day)) / Decimal("30")).quantize(Decimal("0.01"))
        arrears_amount = Decimal(str(attendance.arrears if attendance else 0)) + Decimal(str(arrears or 0))
        pending_salary = (base_pending_salary + arrears_amount).quantize(Decimal("0.01"))
        bonus = (
            (Decimal(str(sal_struct.annual_bonus or 0)) / Decimal("12") if sal_struct else Decimal("0"))
            + Decimal(str(attendance.one_time_bonus if attendance else 0)) + Decimal(str(variable_bonus or 0))
        ).quantize(Decimal("0.01"))

        total_earnings = (pending_salary + leave_encashment + gratuity + bonus + notice_payout).quantize(Decimal("0.01"))
        total_deductions = (notice_recovery + loan_recovery).quantize(Decimal("0.01"))
        net_payable = (total_earnings - total_deductions).quantize(Decimal("0.01"))
        tenure_years = round((exit_obj.last_working_date - emp.joining_date).days / 365.25, 1) if emp.joining_date else 0.0
        return {
            "exit_id": str(exit_id), "employee_id": str(emp.id),
            "employee_name": f"{emp.first_name} {emp.last_name}",
            "joining_date": emp.joining_date.isoformat() if emp.joining_date else None,
            "last_working_date": exit_obj.last_working_date.isoformat(), "tenure_years": tenure_years,
            "basic_monthly": float(basic_monthly), "da_monthly": float(da), "gross_monthly": float(gross_monthly),
            "last_salary": float(gross_monthly), "base_pending_salary": float(base_pending_salary),
            "arrears": float(arrears_amount), "pending_salary": float(pending_salary),
            "leave_encashment": float(leave_encashment), "unused_leave_days": float(unused_leave_days),
            "leave_breakup": [{**item, "days": float(item["days"]), "amount": float(item["amount"])} for item in leave_breakup],
            "gratuity": float(gratuity), "gratuity_ceiling": 2000000.0,
            "bonus": float(bonus), "incentives": float(notice_payout), "recoveries": 0.0,
            "notice_recovery": float(notice_recovery), "notice_payout": float(notice_payout),
            "required_notice_days": required_notice_days, "actual_notice_days": actual_notice_days,
            "notice_shortfall_days": shortfall_days, "notice_waived": bool(waived), "notice_buyout": bool(buyout),
            "asset_recovery": 0.0, "loan_recovery": float(loan_recovery), "other_deductions": 0.0,
            "total_earnings": float(total_earnings), "total_deductions": float(total_deductions),
            "net_payable_amount": float(net_payable), "payment_status": "PENDING",
        }
