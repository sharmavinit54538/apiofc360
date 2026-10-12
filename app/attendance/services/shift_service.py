"""Enterprise Shift and Roster Engine for Face Attendance.

Handles:
- Dynamic shift resolution (Roster overrides, employee shift assignment, company defaults)
- Grace period enforcement
- Late check-in and early check-out calculation
- Overtime calculation
- Overnight shift handling (shifts spanning midnight)
- Holiday and Weekly Off detection
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.utils.time_parse import InvalidTimeFormatError, parse_time_str
from app.attendance.utils.timezone import (
    checkin_window_start,
    checkout_window_end,
    combine_local,
    company_today,
    get_company_tz,
    is_time_in_window,
    now_utc,
    shift_end_datetime,
    shift_start_datetime,
    to_company_local,
)
from app.models.calendar.holiday import HolidayCalendar
from app.models.employee import Employee
from app.models.shift import EmployeeShiftAssignment, Shift
from app.models.shift_plan import EntryApprovalStatus, ShiftPlanEntry, ShiftType

logger = logging.getLogger(__name__)

DEFAULT_GRACE_PERIOD_MINS = 15
DEFAULT_BREAK_MINUTES = 60
FALLBACK_SHIFT_START = time(9, 0)
FALLBACK_SHIFT_END = time(18, 0)

# Shift source types
ShiftSource = Literal["roster", "assignment", "company_default", "fallback"]
OffReason = Literal["roster_off", "weekly_off", "holiday", "leave"]


@dataclass(frozen=True)
class ResolvedShift:
    """Fully resolved shift for a specific business date."""
    shift_id: uuid.UUID | None
    shift_name: str
    source: ShiftSource
    business_date: date
    start_dt: datetime        # tz-aware, company timezone
    end_dt: datetime          # tz-aware; next day when overnight
    is_overnight: bool
    grace_period_mins: int
    break_duration_mins: int
    scheduled_gross_hours: float
    scheduled_net_hours: float          # gross - configured break
    is_off: bool
    off_reason: OffReason | None
    is_holiday: bool
    holiday_name: str | None
    night_shift: bool
    night_premium_percent: float
    working_days: List[str]


@dataclass(frozen=True)
class CheckinEval:
    is_late: bool
    late_minutes: int
    is_off_day_work: bool
    is_holiday_work: bool


@dataclass(frozen=True)
class CheckoutEval:
    working_hours: float
    is_early_checkout: bool
    early_minutes: int
    overtime_hours: float


class ShiftService:
    """Service providing dynamic shift schedules and attendance rule evaluations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_for_date(
        self,
        employee: Employee,
        business_date: date,
        tz,
    ) -> ResolvedShift:
        """Resolve the authoritative shift for an employee on a given business date."""
        company_id = employee.company_id

        # 1. Check roster (published shift plan entries with APPROVED status)
        roster_entry = await self._get_roster_entry(employee.id, business_date, company_id)
        if roster_entry:
            return await self._resolve_from_roster(roster_entry, employee, business_date, tz, company_id)

        # 2. Check effective-dated assignment
        assignment = await self._get_effective_assignment(employee.id, business_date, company_id)
        if assignment:
            return await self._resolve_from_assignment(assignment, employee, business_date, tz, company_id)

        # 3. Check legacy employee.shift_id or employee.shift name
        legacy_shift = await self._get_legacy_shift(employee, company_id)
        if legacy_shift:
            return await self._build_resolved_shift(
                legacy_shift, "company_shifts", employee, business_date, tz, company_id,
                is_off=False, off_reason=None, is_holiday=False, holiday_name=None
            )

        # 4. Check company default shift
        default_shift = await self._get_default_shift(company_id)
        if default_shift:
            return await self._build_resolved_shift(
                default_shift, "company_default", employee, business_date, tz, company_id,
                is_off=False, off_reason=None, is_holiday=False, holiday_name=None
            )

        # 5. Fallback
        logger.warning(
            "No shift found for employee %s on %s, using fallback 09:00-18:00",
            employee.id, business_date
        )
        return self._build_fallback_shift(employee, business_date, tz, company_id)

    async def resolve_range(
        self,
        employee: Employee,
        start_date: date,
        end_date: date,
        tz,
    ) -> List[ResolvedShift]:
        """Bulk resolve shifts for a date range (optimized for /me/schedule)."""
        company_id = employee.company_id
        results = []

        # Fetch all relevant data in bulk
        roster_entries = await self._get_roster_entries_range(employee.id, start_date, end_date, company_id)
        assignments = await self._get_assignments_range(employee.id, start_date, end_date, company_id)
        holidays = await self._get_holidays_range(start_date, end_date, employee.branch, company_id)
        leaves = await self._get_approved_leaves_range(employee.id, start_date, end_date, company_id)

        # Build lookup maps
        roster_map = {(e.shift_date): e for e in roster_entries}
        assignment_map = {}
        for a in assignments:
            for d in self._date_range(a.effective_from, a.effective_to or end_date):
                if start_date <= d <= end_date:
                    assignment_map[d] = a

        legacy_shift = await self._get_legacy_shift(employee, company_id)
        default_shift = await self._get_default_shift(company_id)

        for d in self._date_range(start_date, end_date):
            if d in roster_map:
                resolved = await self._resolve_from_roster(roster_map[d], employee, d, tz, company_id)
            elif d in assignment_map:
                resolved = await self._resolve_from_assignment(assignment_map[d], employee, d, tz, company_id)
            elif legacy_shift:
                is_off, off_reason = self._check_off_day(legacy_shift, d, holidays, leaves, employee.branch)
                resolved = await self._build_resolved_shift(
                    legacy_shift, "company_shifts", employee, d, tz, company_id,
                    is_off, off_reason, d in holidays, holidays.get(d)
                )
            elif default_shift:
                is_off, off_reason = self._check_off_day(default_shift, d, holidays, leaves, employee.branch)
                resolved = await self._build_resolved_shift(
                    default_shift, "company_default", employee, d, tz, company_id,
                    is_off, off_reason, d in holidays, holidays.get(d)
                )
            else:
                resolved = self._build_fallback_shift(employee, d, tz, company_id)
            results.append(resolved)

        return results

    async def resolve_for_timestamp(
        self,
        employee: Employee,
        check_time_utc: datetime,
        tz,
    ) -> Tuple[ResolvedShift, date]:
        """Resolve shift for a specific timestamp (handles overnight shifts)."""
        company_id = employee.company_id
        check_time_local = to_company_local(check_time_utc, tz)

        # Check yesterday, today, and tomorrow's shift windows
        for offset in (-1, 0, 1):
            business_date = check_time_local.date() + timedelta(days=offset)
            resolved = await self.resolve_for_date(employee, business_date, tz)

            window_start = checkin_window_start(resolved.start_dt, 120)  # EARLY_CHECKIN_WINDOW_MINS
            window_end = checkout_window_end(resolved.end_dt, 240)  # POST_SHIFT_WINDOW_MINS

            if is_time_in_window(check_time_utc, window_start, window_end):
                return resolved, business_date

        # Fallback to today's shift
        today = company_today(tz)
        resolved = await self.resolve_for_date(employee, today, tz)
        return resolved, today

    def evaluate_checkin(self, resolved: ResolvedShift, check_in_utc: datetime) -> CheckinEval:
        """Evaluate check-in against shift rules."""
        if resolved.is_off or resolved.is_holiday:
            return CheckinEval(
                is_late=False,
                late_minutes=0,
                is_off_day_work=resolved.is_off and not resolved.is_holiday,
                is_holiday_work=resolved.is_holiday,
            )

        # Compare timezone-aware datetimes
        grace_threshold = resolved.start_dt + timedelta(minutes=resolved.grace_period_mins)

        if check_in_utc > grace_threshold:
            late_delta = check_in_utc - resolved.start_dt
            late_minutes = max(0, int(late_delta.total_seconds() / 60))
            return CheckinEval(
                is_late=True,
                late_minutes=late_minutes,
                is_off_day_work=False,
                is_holiday_work=False,
            )

        return CheckinEval(
            is_late=False,
            late_minutes=0,
            is_off_day_work=False,
            is_holiday_work=False,
        )

    def evaluate_checkout(
        self,
        resolved: ResolvedShift,
        check_in_utc: datetime,
        check_out_utc: datetime,
        logged_break_hours: float,
    ) -> CheckoutEval:
        """Evaluate check-out: early departure, overtime."""
        if resolved.is_off or resolved.is_holiday:
            gross_hours = (check_out_utc - check_in_utc).total_seconds() / 3600.0
            return CheckoutEval(
                working_hours=max(0, gross_hours),
                is_early_checkout=False,
                early_minutes=0,
                overtime_hours=0.0,
            )

        # Gross worked hours
        gross_hours = (check_out_utc - check_in_utc).total_seconds() / 3600.0
        gross_hours = max(0, gross_hours)

        # Effective break: use logged breaks if any, else configured shift break
        # Only auto-deduct configured break if gross >= threshold
        from app.core.config import settings
        if logged_break_hours > 0:
            effective_break = logged_break_hours
        elif gross_hours >= settings.ATTENDANCE_AUTO_BREAK_MIN_GROSS_HOURS:
            effective_break = resolved.break_duration_mins / 60.0
        else:
            effective_break = 0.0

        working_hours = max(0, gross_hours - effective_break)

        # Overtime
        overtime_hours = max(0, round(working_hours - resolved.scheduled_net_hours, 2))

        # Early checkout
        expected_end = resolved.end_dt
        is_early = check_out_utc < expected_end
        early_minutes = max(0, int((expected_end - check_out_utc).total_seconds() / 60)) if is_early else 0

        return CheckoutEval(
            working_hours=round(working_hours, 2),
            is_early_checkout=is_early,
            early_minutes=early_minutes,
            overtime_hours=round(overtime_hours, 2),
        )

    # --- Private helper methods ---

    async def _get_roster_entry(
        self, employee_id: uuid.UUID, business_date: date, company_id: uuid.UUID
    ) -> ShiftPlanEntry | None:
        stmt = select(ShiftPlanEntry).where(
            and_(
                ShiftPlanEntry.employee_id == employee_id,
                ShiftPlanEntry.shift_date == business_date,
                ShiftPlanEntry.approval_status == EntryApprovalStatus.APPROVED,
                ShiftPlanEntry.company_id == company_id,
            )
        ).join(ShiftPlanEntry.plan).where(
            ShiftPlanEntry.plan.has(status="PUBLISHED")
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _get_roster_entries_range(
        self, employee_id: uuid.UUID, start: date, end: date, company_id: uuid.UUID
    ) -> List[ShiftPlanEntry]:
        stmt = select(ShiftPlanEntry).where(
            and_(
                ShiftPlanEntry.employee_id == employee_id,
                ShiftPlanEntry.shift_date >= start,
                ShiftPlanEntry.shift_date <= end,
                ShiftPlanEntry.approval_status == EntryApprovalStatus.APPROVED,
                ShiftPlanEntry.company_id == company_id,
            )
        ).join(ShiftPlanEntry.plan).where(
            ShiftPlanEntry.plan.has(status="PUBLISHED")
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_effective_assignment(
        self, employee_id: uuid.UUID, business_date: date, company_id: uuid.UUID
    ) -> EmployeeShiftAssignment | None:
        stmt = select(EmployeeShiftAssignment).where(
            and_(
                EmployeeShiftAssignment.employee_id == employee_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_from <= business_date,
                or_(
                    EmployeeShiftAssignment.effective_to.is_(None),
                    EmployeeShiftAssignment.effective_to >= business_date,
                ),
            )
        ).order_by(EmployeeShiftAssignment.effective_from.desc())
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _get_assignments_range(
        self, employee_id: uuid.UUID, start: date, end: date, company_id: uuid.UUID
    ) -> List[EmployeeShiftAssignment]:
        stmt = select(EmployeeShiftAssignment).where(
            and_(
                EmployeeShiftAssignment.employee_id == employee_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_from <= end,
                or_(
                    EmployeeShiftAssignment.effective_to.is_(None),
                    EmployeeShiftAssignment.effective_to >= start,
                ),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_legacy_shift(
        self, employee: Employee, company_id: uuid.UUID
    ) -> Shift | None:
        # Try shift_id first
        if employee.shift_id:
            stmt = select(Shift).where(
                and_(
                    Shift.id == employee.shift_id,
                    Shift.company_id == company_id,
                    Shift.deleted_at.is_(None),
                )
            )
            result = await self.db.execute(stmt)
            shift = result.scalars().first()
            if shift:
                return shift

        # Fallback to shift name (case-insensitive exact match)
        if employee.shift:
            stmt = select(Shift).where(
                and_(
                    Shift.company_id == company_id,
                    Shift.deleted_at.is_(None),
                    func.lower(Shift.name) == employee.shift.strip().lower(),
                )
            )
            result = await self.db.execute(stmt)
            return result.scalars().first()

        return None

    async def _get_default_shift(self, company_id: uuid.UUID) -> Shift | None:
        stmt = select(Shift).where(
            and_(
                Shift.company_id == company_id,
                Shift.is_default.is_(True),
                Shift.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _get_holidays_range(
        self, start: date, end: date, branch: str | None, company_id: uuid.UUID
    ) -> Dict[date, str]:
        stmt = select(HolidayCalendar).where(
            and_(
                HolidayCalendar.company_id == company_id,
                HolidayCalendar.holiday_date >= start,
                HolidayCalendar.holiday_date <= end,
            )
        )
        if branch:
            stmt = stmt.where(
                or_(HolidayCalendar.branch.is_(None), HolidayCalendar.branch == branch)
            )
        result = await self.db.execute(stmt)
        holidays = result.scalars().all()
        return {h.holiday_date: h.holiday_name for h in holidays}

    async def _get_approved_leaves_range(
        self, employee_id: uuid.UUID, start: date, end: date, company_id: uuid.UUID
    ) -> List[date]:
        # Try to find leave request model - skip if not available
        try:
            from app.models.leave import LeaveRequest, LeaveStatus
            stmt = select(LeaveRequest).where(
                and_(
                    LeaveRequest.employee_id == employee_id,
                    LeaveRequest.status == LeaveStatus.APPROVED,
                    LeaveRequest.start_date <= end,
                    LeaveRequest.end_date >= start,
                )
            )
            result = await self.db.execute(stmt)
            leaves = result.scalars().all()
            leave_dates = []
            for leave in leaves:
                current = max(leave.start_date, start)
                while current <= min(leave.end_date, end):
                    leave_dates.append(current)
                    current += timedelta(days=1)
            return leave_dates
        except ImportError:
            return []

    def _date_range(self, start: date, end: date):
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)

    def _check_off_day(
        self,
        shift: Shift,
        business_date: date,
        holidays: Dict[date, str],
        leave_dates: List[date],
        branch: str | None,
    ) -> Tuple[bool, OffReason | None]:
        # Holiday takes precedence
        if business_date in holidays:
            return True, "holiday"
        # Approved leave
        if business_date in leave_dates:
            return True, "leave"
        # Weekly off (day not in shift's working_days)
        weekday_abbr = business_date.strftime("%a")
        if weekday_abbr not in shift.working_days:
            return True, "weekly_off"
        return False, None

    async def _resolve_from_roster(
        self,
        entry: ShiftPlanEntry,
        employee: Employee,
        business_date: date,
        tz,
        company_id: uuid.UUID,
    ) -> ResolvedShift:
        # OFF/WEEKLY_OFF/HOLIDAY/LEAVE types mean no work
        is_off = entry.shift_type in {
            ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY, ShiftType.LEAVE
        }

        if entry.shift_id:
            stmt = select(Shift).where(
                and_(Shift.id == entry.shift_id, Shift.deleted_at.is_(None))
            )
            result = await self.db.execute(stmt)
            shift = result.scalars().first()
            if shift:
                return await self._build_resolved_shift(
                    shift, "roster", employee, business_date, tz, company_id,
                    is_off, "roster_off" if is_off else None,
                    entry.shift_type == ShiftType.HOLIDAY, None
                )

        # Fallback to shift_type for times
        if entry.start_time and entry.end_time:
            # Build a virtual shift from entry times
            return ResolvedShift(
                shift_id=None,
                shift_name=f"Roster: {entry.shift_type.value}",
                source="roster",
                business_date=business_date,
                start_dt=combine_local(business_date, entry.start_time, tz),
                end_dt=shift_end_datetime(business_date, entry.start_time, entry.end_time, entry.end_time < entry.start_time, tz),
                is_overnight=entry.end_time < entry.start_time,
                grace_period_mins=DEFAULT_GRACE_PERIOD_MINS,
                break_duration_mins=DEFAULT_BREAK_MINUTES,
                scheduled_gross_hours=round((shift_end_datetime(business_date, entry.start_time, entry.end_time, entry.end_time < entry.start_time, tz) - combine_local(business_date, entry.start_time, tz)).total_seconds() / 3600.0, 2),
                scheduled_net_hours=round(max(0, ((shift_end_datetime(business_date, entry.start_time, entry.end_time, entry.end_time < entry.start_time, tz) - combine_local(business_date, entry.start_time, tz)).total_seconds() / 3600.0) - (DEFAULT_BREAK_MINUTES / 60.0)), 2),
                is_off=is_off,
                off_reason="roster_off" if is_off else None,
                is_holiday=entry.shift_type == ShiftType.HOLIDAY,
                holiday_name=None,
                night_shift=entry.shift_type == ShiftType.NIGHT,
                night_premium_percent=0.0,
                working_days=[],
            )

        # Ultimate fallback
        return self._build_fallback_shift(employee, business_date, tz, company_id)

    async def _resolve_from_assignment(
        self,
        assignment: EmployeeShiftAssignment,
        employee: Employee,
        business_date: date,
        tz,
        company_id: uuid.UUID,
    ) -> ResolvedShift:
        stmt = select(Shift).where(
            and_(Shift.id == assignment.shift_id, Shift.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        shift = result.scalars().first()
        if not shift:
            return self._build_fallback_shift(employee, business_date, tz, company_id)

        # Check off days
        holidays = await self._get_holidays_range(business_date, business_date, employee.branch, company_id)
        leaves = await self._get_approved_leaves_range(employee.id, business_date, business_date, company_id)
        is_off, off_reason = self._check_off_day(shift, business_date, holidays, leaves, employee.branch)

        return await self._build_resolved_shift(
            shift, "assignment", employee, business_date, tz, company_id,
            is_off, off_reason, business_date in holidays, holidays.get(business_date)
        )

    async def _build_resolved_shift(
        self,
        shift: Shift,
        source: ShiftSource,
        employee: Employee,
        business_date: date,
        tz,
        company_id: uuid.UUID,
        is_off: bool,
        off_reason: OffReason | None,
        is_holiday: bool,
        holiday_name: str | None,
    ) -> ResolvedShift:
        start_dt = shift_start_datetime(business_date, shift.start_time, tz)
        end_dt = shift_end_datetime(business_date, shift.start_time, shift.end_time, shift.is_overnight, tz)
        gross_hours = round((end_dt - start_dt).total_seconds() / 3600.0, 2)
        net_hours = round(max(0, gross_hours - (shift.break_duration_minutes / 60.0)), 2)

        return ResolvedShift(
            shift_id=shift.id,
            shift_name=shift.name,
            source=source,
            business_date=business_date,
            start_dt=start_dt,
            end_dt=end_dt,
            is_overnight=shift.is_overnight,
            grace_period_mins=shift.grace_period_minutes,
            break_duration_mins=shift.break_duration_minutes,
            scheduled_gross_hours=gross_hours,
            scheduled_net_hours=net_hours,
            is_off=is_off,
            off_reason=off_reason,
            is_holiday=is_holiday,
            holiday_name=holiday_name,
            night_shift=shift.is_night_shift,
            night_premium_percent=float(shift.night_premium_percent),
            working_days=shift.working_days,
        )

    def _build_fallback_shift(
        self,
        employee: Employee,
        business_date: date,
        tz,
        company_id: uuid.UUID,
    ) -> ResolvedShift:
        start_dt = combine_local(business_date, FALLBACK_SHIFT_START, tz)
        end_dt = combine_local(business_date, FALLBACK_SHIFT_END, tz)
        gross_hours = round((end_dt - start_dt).total_seconds() / 3600.0, 2)
        net_hours = round(max(0, gross_hours - (DEFAULT_BREAK_MINUTES / 60.0)), 2)

        # Check if fallback day is off
        weekday_abbr = business_date.strftime("%a")
        is_off = weekday_abbr not in ["Mon", "Tue", "Wed", "Thu", "Fri"]
        off_reason: OffReason = "weekly_off" if is_off else None

        return ResolvedShift(
            shift_id=None,
            shift_name="General Shift (Fallback)",
            source="fallback",
            business_date=business_date,
            start_dt=start_dt,
            end_dt=end_dt,
            is_overnight=False,
            grace_period_mins=DEFAULT_GRACE_PERIOD_MINS,
            break_duration_mins=DEFAULT_BREAK_MINUTES,
            scheduled_gross_hours=gross_hours,
            scheduled_net_hours=net_hours,
            is_off=is_off,
            off_reason=off_reason,
            is_holiday=False,
            holiday_name=None,
            night_shift=False,
            night_premium_percent=0.0,
            working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        )

# Need to import func
from sqlalchemy import func