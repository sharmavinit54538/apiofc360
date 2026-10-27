"""Synchronise locked attendance into immutable, approved variable-pay inputs."""
from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee
from app.models.leave import CompOffLedger
from app.models.payroll import OvertimeEntry, OvertimePolicy, SalaryStructure
from app.models.payroll_models import Compensation, PayrollPeriod, VariableInput
from app.models.shift import Shift, ShiftAllowancePolicy
from app.services.payroll.money import as_decimal, round_paise


class AttendanceToPayrollSyncService:
    SOURCE = "ATTENDANCE_LOCK"
    STANDARD_DAYS = Decimal("30")
    HOURS_PER_DAY = Decimal("8")
    OT_TYPES = frozenset({"APPROVED", "PUSHED"})

    @classmethod
    def calculate_overtime_paise(
        cls,
        *,
        basic_monthly_paise: int,
        ot_hours: Any,
        multiplier: Any = Decimal("1.5"),
        gross_monthly_paise: Optional[int] = None,
        use_gross: bool = False,
        working_days: Any = STANDARD_DAYS,
        hours_per_day: Any = HOURS_PER_DAY,
    ) -> int:
        """Calculate OT from hourly Basic (or Gross) using Decimal arithmetic."""
        monthly = gross_monthly_paise if use_gross and gross_monthly_paise is not None else basic_monthly_paise
        hourly = Decimal(int(monthly or 0)) / (as_decimal(working_days) * as_decimal(hours_per_day))
        return round_paise(hourly * as_decimal(ot_hours) * as_decimal(multiplier))

    @staticmethod
    def _period_bounds(period) -> tuple[date, date]:
        if getattr(period, "start_date", None) and getattr(period, "end_date", None):
            return period.start_date, period.end_date
        last = calendar.monthrange(period.period_year, period.period_month)[1]
        return date(period.period_year, period.period_month, 1), date(period.period_year, period.period_month, last)

    @staticmethod
    def _monthly_compensation(comp, salary=None) -> tuple[int, int]:
        if comp is not None:
            basic = int(comp.basic_monthly_paise or 0)
            gross = basic + int(comp.hra_monthly_paise or 0) + int(comp.special_allowance_monthly_paise or 0)
            return basic, gross
        if salary is not None:
            basic = round_paise(as_decimal(salary.basic_monthly) * 100)
            gross = round_paise(sum(as_decimal(getattr(salary, f, 0)) for f in (
                "basic_monthly", "hra_monthly", "special_allowance_monthly", "conveyance_monthly"
            )) * 100)
            return basic, gross
        return 0, 0

    @classmethod
    async def _upsert(
        cls,
        session: AsyncSession,
        *,
        period,
        employee_id: uuid.UUID,
        input_type: str,
        amount_paise: int,
        units: Any = None,
        rate_per_unit_paise: Optional[int] = None,
        description: str,
        now: datetime,
    ) -> VariableInput:
        stmt = select(VariableInput).where(
            VariableInput.period_id == period.id,
            VariableInput.employee_id == employee_id,
            VariableInput.type == input_type,
            VariableInput.source == cls.SOURCE,
        )
        row = (await session.execute(stmt)).scalars().first()
        if row is None:
            row = VariableInput(
                id=uuid.uuid4(),
                employee_id=employee_id,
                company_id=period.company_id,
                period_id=period.id,
                type=input_type,
                amount_paise=int(amount_paise),
                description=description,
                source=cls.SOURCE,
            )
            session.add(row)
        row.amount_paise = int(amount_paise)
        row.units = as_decimal(units) if units is not None else None
        row.rate_per_unit_paise = rate_per_unit_paise
        row.description = description
        row.status = "APPROVED"
        row.is_locked = True
        row.source = cls.SOURCE
        row.approved_at = now
        row.remarks = "Generated and locked by attendance-to-payroll synchronisation"
        await session.flush()
        return row

    @classmethod
    async def sync_on_attendance_lock(
        cls,
        session: AsyncSession,
        period_or_id,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Aggregate approved OT, eligible shifts and encashed comp-offs.

        Re-running this method is safe: each employee/period/type has one
        system-owned row and its paise value is replaced from source records.
        """
        if isinstance(period_or_id, uuid.UUID):
            period = await session.get(PayrollPeriod, period_or_id)
            if period is None:
                from app.models.payroll import PayCycle
                period = await session.get(PayCycle, period_or_id)
        else:
            period = period_or_id
        if period is None:
            raise ValueError("Payroll period is required for attendance synchronisation")

        start_date, end_date = cls._period_bounds(period)
        now = datetime.now(timezone.utc)
        company_id = period.company_id

        comp_rows = (await session.execute(
            select(Compensation).where(Compensation.status == "ACTIVE")
        )).scalars().all()
        comp_by_employee = {c.employee_id: c for c in comp_rows if company_id is None or c.company_id == company_id}
        salary_rows = (await session.execute(
            select(SalaryStructure).where(SalaryStructure.is_active == True)  # noqa: E712
        )).scalars().all()
        salary_by_employee = {s.employee_id: s for s in salary_rows if company_id is None or s.company_id == company_id}

        # Approved monthly OT aggregates.  PUSHED is included so a retry after
        # a crash remains idempotent rather than dropping the original input.
        ot_stmt = select(OvertimeEntry).where(
            OvertimeEntry.period_month == period.period_month,
            OvertimeEntry.period_year == period.period_year,
            OvertimeEntry.status.in_(tuple(cls.OT_TYPES)),
        )
        if company_id is not None:
            ot_stmt = ot_stmt.where(OvertimeEntry.company_id == company_id)
        ot_entries = (await session.execute(ot_stmt)).scalars().all()

        policies = (await session.execute(
            select(OvertimePolicy).where(OvertimePolicy.is_active == True)  # noqa: E712
        )).scalars().all()
        employee_ids = {e.employee_id for e in ot_entries}
        employees = {}
        if employee_ids:
            employees = {e.id: e for e in (await session.execute(select(Employee).where(Employee.id.in_(employee_ids)))).scalars().all()}

        totals: dict[uuid.UUID, dict[str, Any]] = {}
        for entry in ot_entries:
            emp = employees.get(entry.employee_id)
            comp = comp_by_employee.get(entry.employee_id)
            basic, gross = cls._monthly_compensation(comp, salary_by_employee.get(entry.employee_id))
            applicable = [p for p in policies if (p.company_id is None or p.company_id == company_id)]
            if emp is not None:
                specific = [p for p in applicable if
                            (p.applicable_role is None or p.applicable_role == getattr(emp, "role", None))
                            and (p.applicable_grade is None or p.applicable_grade == getattr(emp, "grade", None))]
                if specific:
                    applicable = specific
            # Tenant-specific and role/grade-specific policies take precedence
            # over global/generic rows; UUID is a deterministic final tie-break.
            applicable.sort(key=lambda p: (
                p.company_id != company_id,
                int(p.applicable_role is None) + int(p.applicable_grade is None),
                str(p.id),
            ))
            policy = applicable[0] if applicable else None
            multiplier = policy.rate_multiplier if policy else Decimal("1.5")
            rate_base = str(getattr(policy, "rate_base", "BASIC") or "BASIC").upper()
            use_gross = rate_base in {"GROSS", "GROSS_SALARY", "GROSS_MONTHLY"}
            hours = entry.adjusted_hours if entry.adjusted_hours is not None else entry.ot_hours
            amount = cls.calculate_overtime_paise(
                basic_monthly_paise=basic,
                gross_monthly_paise=gross,
                ot_hours=hours or 0,
                multiplier=multiplier,
                use_gross=use_gross,
                working_days=getattr(policy, "working_days", cls.STANDARD_DAYS) if policy else cls.STANDARD_DAYS,
                hours_per_day=getattr(policy, "hours_per_day", cls.HOURS_PER_DAY) if policy else cls.HOURS_PER_DAY,
            )
            bucket = totals.setdefault(entry.employee_id, {"OVERTIME": 0, "SHIFT_ALLOWANCE": 0, "COMP_OFF_ENCASHMENT": 0, "ot_hours": Decimal("0"), "shift_days": Decimal("0"), "comp_off_days": Decimal("0"), "ot_rate": 0})
            bucket["OVERTIME"] += amount
            bucket["ot_hours"] += as_decimal(hours or 0)
            bucket["ot_rate"] = round_paise(Decimal(amount) / as_decimal(hours)) if hours else 0

        # Shift allowances are earned per eligible attended day.
        att_stmt = select(Attendance).where(Attendance.date >= start_date, Attendance.date <= end_date)
        if company_id is not None:
            att_stmt = att_stmt.where(Attendance.company_id == company_id)
        attendance_rows = (await session.execute(att_stmt)).scalars().all()
        shift_policies = (await session.execute(
            select(ShiftAllowancePolicy).where(ShiftAllowancePolicy.is_active == True)  # noqa: E712
        )).scalars().all()
        shift_cache: dict[uuid.UUID, Shift | None] = {}
        for attendance in attendance_rows:
            if str(attendance.status or "").upper() in {"ABSENT", "CANCELLED", "REJECTED"}:
                continue
            shift = None
            if attendance.shift_id:
                if attendance.shift_id not in shift_cache:
                    shift_cache[attendance.shift_id] = await session.get(Shift, attendance.shift_id)
                shift = shift_cache[attendance.shift_id]
            names = {str(attendance.shift_name or "").upper(), str(getattr(shift, "code", "") or "").upper(), str(getattr(shift, "name", "") or "").upper()}
            if getattr(shift, "is_night_shift", False):
                names.add("NIGHT")
            if attendance.is_off_day_work:
                names.add("WEEKEND")
            if attendance.is_holiday_work:
                names.add("HOLIDAY")
            candidates = []
            for policy in shift_policies:
                if policy.company_id is not None and policy.company_id != company_id:
                    continue
                if policy.effective_from and policy.effective_from > attendance.date:
                    continue
                if policy.effective_to and policy.effective_to < attendance.date:
                    continue
                if policy.shift_id and policy.shift_id == attendance.shift_id:
                    candidates.append(policy)
                elif not policy.shift_id and str(policy.shift_type).upper() in names:
                    candidates.append(policy)
            if not candidates:
                continue
            # A shift-specific rule wins over a general type rule; otherwise
            # the first deterministic policy is the single daily allowance.
            candidates.sort(key=lambda p: (p.shift_id is None, str(p.id)))
            policy = candidates[0]
            bucket = totals.setdefault(attendance.employee_id, {"OVERTIME": 0, "SHIFT_ALLOWANCE": 0, "COMP_OFF_ENCASHMENT": 0, "ot_hours": Decimal("0"), "shift_days": Decimal("0"), "comp_off_days": Decimal("0"), "ot_rate": 0})
            bucket["SHIFT_ALLOWANCE"] += int(policy.allowance_paise or 0)
            bucket["shift_days"] += Decimal("1")

        comp_stmt = select(CompOffLedger).where(CompOffLedger.status == "ENCASHED")
        if company_id is not None:
            comp_stmt = comp_stmt.where(CompOffLedger.company_id == company_id)
        comp_offs = (await session.execute(comp_stmt)).scalars().all()
        for credit in comp_offs:
            effective_date = credit.encashed_at.date() if credit.encashed_at else credit.worked_date
            if not (start_date <= effective_date <= end_date):
                continue
            bucket = totals.setdefault(credit.employee_id, {"OVERTIME": 0, "SHIFT_ALLOWANCE": 0, "COMP_OFF_ENCASHMENT": 0, "ot_hours": Decimal("0"), "shift_days": Decimal("0"), "comp_off_days": Decimal("0"), "ot_rate": 0})
            encashment_paise = int(credit.encashment_amount_paise or 0)
            if encashment_paise == 0:
                # Older comp-off rows recorded only the credit days.  Use the
                # same deterministic gross/30 daily-rate fallback as arrears.
                _basic, gross = cls._monthly_compensation(
                    comp_by_employee.get(credit.employee_id), salary_by_employee.get(credit.employee_id)
                )
                encashment_paise = round_paise(Decimal(gross) / cls.STANDARD_DAYS * as_decimal(credit.credit_days or 0))
            bucket["COMP_OFF_ENCASHMENT"] += encashment_paise
            bucket["comp_off_days"] += as_decimal(credit.credit_days or 0)

        rows: list[VariableInput] = []
        for employee_id, bucket in totals.items():
            for input_type, units, rate, description in (
                ("OVERTIME", bucket["ot_hours"], bucket["ot_rate"], "Attendance-lock approved overtime"),
                ("SHIFT_ALLOWANCE", bucket["shift_days"], None, "Attendance-lock eligible shift allowance"),
                ("COMP_OFF_ENCASHMENT", bucket["comp_off_days"], None, "Attendance-lock comp-off encashment"),
            ):
                # Do not create empty rows for employees who only have another
                # kind of input; existing system rows are zeroed to avoid stale
                # values when a source approval is reversed.
                existing = (await session.execute(select(VariableInput).where(
                    VariableInput.period_id == period.id,
                    VariableInput.employee_id == employee_id,
                    VariableInput.type == input_type,
                    VariableInput.source == cls.SOURCE,
                ))).scalars().first()
                if bucket[input_type] == 0 and existing is None:
                    continue
                rows.append(await cls._upsert(
                    session, period=period, employee_id=employee_id, input_type=input_type,
                    amount_paise=bucket[input_type], units=units, rate_per_unit_paise=rate,
                    description=description, now=now,
                ))

        # Mark OT as pushed only after all variable rows have been flushed.
        for entry in ot_entries:
            if entry.status == "APPROVED":
                entry.status = "PUSHED"
        if commit:
            await session.commit()
        return {
            "period_id": str(period.id),
            "employee_count": len(totals),
            "variable_input_count": len(rows),
            "overtime_paise": sum(int(b["OVERTIME"]) for b in totals.values()),
            "shift_allowance_paise": sum(int(b["SHIFT_ALLOWANCE"]) for b in totals.values()),
            "comp_off_encashment_paise": sum(int(b["COMP_OFF_ENCASHMENT"]) for b in totals.values()),
            "variable_input_ids": [str(r.id) for r in rows],
        }

    # Common aliases used by jobs and API integrations.
    sync = sync_on_attendance_lock
    sync_period = sync_on_attendance_lock


AttendanceToPayrollService = AttendanceToPayrollSyncService
