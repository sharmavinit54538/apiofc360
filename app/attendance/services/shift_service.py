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
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar.holiday import HolidayCalendar
from app.models.employee import Employee
from app.models.onboarding import Shift
from app.models.shift_plan import ShiftPlanEntry

logger = logging.getLogger(__name__)

DEFAULT_SHIFT_START = time(9, 0)
DEFAULT_SHIFT_END = time(18, 0)
DEFAULT_GRACE_PERIOD_MINS = 15
DEFAULT_SCHEDULED_HOURS = 8.0


def _parse_time_str(val: Any) -> Optional[time]:
    """Safely parse time from string ('09:00', '09:00:00') or time object."""
    if isinstance(val, time):
        return val
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    try:
        parts = [int(p) for p in val.split(":")[:2]]
        return time(parts[0], parts[1])
    except Exception:
        return None


class ShiftService:
    """Service providing dynamic shift schedules and attendance rule evaluations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_employee_shift(
        self, employee: Employee, target_date: date
    ) -> Dict[str, Any]:
        """Resolves the authoritative shift schedule for an employee on a given date.
        
        Priority 1: ShiftPlanEntry (individual roster override for target_date)
        Priority 2: Employee's assigned shift name matching `shifts` table
        Priority 3: Standard default shift (09:00 to 18:00, 15m grace)
        """
        company_id = employee.company_id
        shift_info: Dict[str, Any] = {
            "shift_id": None,
            "shift_name": "General Shift",
            "start_time": DEFAULT_SHIFT_START,
            "end_time": DEFAULT_SHIFT_END,
            "grace_period_mins": DEFAULT_GRACE_PERIOD_MINS,
            "is_overnight": False,
            "is_off": False,
            "is_holiday": False,
            "holiday_name": None,
            "scheduled_hours": DEFAULT_SCHEDULED_HOURS,
            "source": "default",
        }

        # 1. Check for Holiday on target_date
        holiday_stmt = select(HolidayCalendar).where(HolidayCalendar.holiday_date == target_date)
        if employee.branch:
            holiday_stmt = holiday_stmt.where(
                (HolidayCalendar.branch.is_(None)) | (HolidayCalendar.branch == employee.branch)
            )
        holiday_res = await self.db.execute(holiday_stmt)
        holiday = holiday_res.scalars().first()
        if holiday:
            shift_info["is_holiday"] = True
            shift_info["holiday_name"] = holiday.holiday_name

        # 2. Priority 1: Check ShiftPlanEntry (roster override)
        roster_stmt = (
            select(ShiftPlanEntry)
            .where(
                and_(
                    ShiftPlanEntry.employee_id == employee.id,
                    ShiftPlanEntry.shift_date == target_date,
                )
            )
        )
        roster_res = await self.db.execute(roster_stmt)
        roster_entry = roster_res.scalars().first()

        if roster_entry:
            shift_info["source"] = "roster_entry"
            shift_info["shift_name"] = f"Roster: {roster_entry.shift_type}"
            if roster_entry.shift_type.upper() in {"OFF", "WEEKLY_OFF", "HOLIDAY"}:
                shift_info["is_off"] = True

            if roster_entry.start_time and roster_entry.end_time:
                shift_info["start_time"] = roster_entry.start_time
                shift_info["end_time"] = roster_entry.end_time
            return self._finalize_shift_metrics(shift_info, target_date)

        # 3. Priority 2: Check employee's assigned shift in DB
        assigned_shift_name = getattr(employee, "shift", None)
        if assigned_shift_name and company_id:
            shift_stmt = select(Shift).where(
                and_(
                    Shift.company_id == company_id,
                    Shift.name.ilike(assigned_shift_name.strip()),
                )
            )
            shift_res = await self.db.execute(shift_stmt)
            db_shift = shift_res.scalars().first()

            if db_shift:
                parsed_start = _parse_time_str(db_shift.start_time)
                parsed_end = _parse_time_str(db_shift.end_time)
                if parsed_start and parsed_end:
                    shift_info["shift_id"] = db_shift.id
                    shift_info["shift_name"] = db_shift.name
                    shift_info["start_time"] = parsed_start
                    shift_info["end_time"] = parsed_end
                    shift_info["source"] = "company_shifts"
                    return self._finalize_shift_metrics(shift_info, target_date)

        # 4. Priority 3: Fallback to weekly off check (e.g. Sunday = 6)
        if target_date.weekday() == 6:  # Sunday
            shift_info["is_off"] = True

        return self._finalize_shift_metrics(shift_info, target_date)

    def _finalize_shift_metrics(self, info: Dict[str, Any], target_date: date) -> Dict[str, Any]:
        """Calculates overnight flag and scheduled hours."""
        start_t = info["start_time"]
        end_t = info["end_time"]

        # Overnight shift check (e.g., 20:00 to 05:00)
        is_overnight = end_t < start_t
        info["is_overnight"] = is_overnight

        # Scheduled duration in hours
        start_dt = datetime.combine(target_date, start_t)
        if is_overnight:
            end_dt = datetime.combine(target_date + timedelta(days=1), end_t)
        else:
            end_dt = datetime.combine(target_date, end_t)

        scheduled_hrs = round((end_dt - start_dt).total_seconds() / 3600.0, 2)
        # Deduct standard 1-hr meal break if shift is >= 8 hours
        net_scheduled = max(1.0, scheduled_hrs - 1.0) if scheduled_hrs >= 8.0 else scheduled_hrs
        info["scheduled_hours"] = net_scheduled
        return info

    def evaluate_checkin(
        self,
        shift_info: Dict[str, Any],
        check_in_time: datetime,
        target_date: date,
    ) -> Tuple[bool, int]:
        """Evaluates whether check-in is late based on shift start and grace period.
        
        Returns:
            (is_late: bool, late_minutes: int)
        """
        start_t = shift_info["start_time"]
        grace_mins = shift_info["grace_period_mins"]

        # Convert to same timezone context (strip tz for naive comparison with shift_start)
        if check_in_time.tzinfo is not None:
            # Shift timings are local to employee/company, compare with local wall time
            local_checkin_time = check_in_time.time()
        else:
            local_checkin_time = check_in_time.time()

        shift_start_dt = datetime.combine(target_date, start_t)
        grace_threshold_dt = shift_start_dt + timedelta(minutes=grace_mins)

        check_in_dt = datetime.combine(target_date, local_checkin_time)

        if check_in_dt > grace_threshold_dt:
            late_delta = check_in_dt - shift_start_dt
            late_minutes = max(0, int(late_delta.total_seconds() / 60))
            return True, late_minutes

        return False, 0

    def evaluate_checkout(
        self,
        shift_info: Dict[str, Any],
        check_out_time: datetime,
        target_date: date,
        net_working_hours: float,
    ) -> Dict[str, Any]:
        """Evaluates early checkout and overtime hours against shift."""
        end_t = shift_info["end_time"]
        is_overnight = shift_info.get("is_overnight", False)

        checkout_local_time = check_out_time.time()
        if is_overnight:
            expected_end_dt = datetime.combine(target_date + timedelta(days=1), end_t)
        else:
            expected_end_dt = datetime.combine(target_date, end_t)

        actual_checkout_dt = datetime.combine(target_date, checkout_local_time)

        is_early = actual_checkout_dt < expected_end_dt
        early_minutes = max(0, int((expected_end_dt - actual_checkout_dt).total_seconds() / 60)) if is_early else 0

        scheduled_hrs = shift_info.get("scheduled_hours", DEFAULT_SCHEDULED_HOURS)
        overtime_hours = max(0.0, round(net_working_hours - scheduled_hrs, 2))

        return {
            "is_early_checkout": is_early,
            "early_minutes": early_minutes,
            "overtime_hours": overtime_hours,
        }
