"""Daily Face Attendance analytics service."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.calendar.holiday import HolidayCalendar
from app.models.core_modules import Holiday
from app.models.employee import Employee
from app.models.leave import LeaveRequest


class AttendanceAnalyticsService:
    """Calculates attendance dashboard KPIs and overview trends."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _parse_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
        if not value:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value).strip())
        except (ValueError, TypeError):
            return None

    def _employee_filter_conditions(
        self,
        company_id: uuid.UUID,
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> list[Any]:
        """Build tenant-safe active employee filter conditions with optional dimension filters."""
        conditions: list[Any] = [
            Employee.company_id == company_id,
            Employee.is_deleted == False,  # noqa: E712
            Employee.status == "ACTIVE",
        ]
        if department_id and str(department_id).strip().lower() not in {"all", ""}:
            dept_val = str(department_id).strip()
            dept_uuid = self._parse_uuid(dept_val)
            if dept_uuid is not None:
                conditions.append(
                    or_(Employee.department_id == dept_uuid, func.lower(Employee.department) == dept_val.lower())
                )
            else:
                conditions.append(func.lower(Employee.department) == dept_val.lower())

        if shift_id and str(shift_id).strip().lower() not in {"all", ""}:
            shift_val = str(shift_id).strip()
            shift_uuid = self._parse_uuid(shift_val)
            if shift_uuid is not None:
                conditions.append(
                    or_(Employee.shift_id == shift_uuid, func.lower(Employee.shift) == shift_val.lower())
                )
            else:
                conditions.append(func.lower(Employee.shift) == shift_val.lower())

        if location_id and str(location_id).strip().lower() not in {"all", ""}:
            loc_val = str(location_id).strip()
            loc_uuid = self._parse_uuid(loc_val)
            if loc_uuid is not None:
                conditions.append(
                    or_(
                        Employee.branch_id == loc_uuid,
                        func.lower(Employee.work_location) == loc_val.lower(),
                        func.lower(Employee.branch) == loc_val.lower(),
                    )
                )
            else:
                conditions.append(
                    or_(
                        func.lower(Employee.work_location) == loc_val.lower(),
                        func.lower(Employee.branch) == loc_val.lower(),
                    )
                )
        return conditions

    async def get_company_analytics(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Fetch today's statistics, checked-in count, absent count, and presence rates."""
        today = date.today()
        total_active = await self._get_total_active_employees(company_id)
        holidays = await self._get_holiday_dates(company_id, today, today)
        leave_counts = await self._get_leave_counts_by_date(company_id, today, today)
        on_leave = leave_counts.get(today, 0)

        agg = (
            await self.db.execute(
                select(
                    func.count(Attendance.id).label("total_marked"),
                    func.coalesce(
                        func.sum(case((func.lower(Attendance.status) != "absent", 1), else_=0)), 0
                    ).label("present_count"),
                    func.coalesce(
                        func.sum(case((Attendance.check_out_time.isnot(None), 1), else_=0)), 0
                    ).label("checked_out_count"),
                    func.coalesce(
                        func.sum(
                            case(
                                (or_(Attendance.is_late.is_(True), func.lower(Attendance.status) == "late"), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("late_count"),
                    func.coalesce(func.avg(Attendance.working_hours), 0.0).label("avg_working_hours"),
                )
                .select_from(Attendance)
                .join(Employee, Attendance.employee_id == Employee.id)
                .where(
                    and_(
                        Attendance.date == today,
                        (Attendance.company_id == company_id) | (Employee.company_id == company_id),
                        Employee.is_deleted == False,  # noqa: E712
                    )
                )
            )
        ).one()

        checked_in = int(agg.present_count or 0)
        checked_out = int(agg.checked_out_count or 0)
        late = int(agg.late_count or 0)
        on_leave_clamped = min(on_leave, max(0, total_active - checked_in))
        is_working_day = today.weekday() < 5 and today not in holidays
        absent = max(0, total_active - checked_in - on_leave_clamped) if is_working_day else 0
        rate = round((checked_in / total_active) * 100.0, 2) if total_active > 0 else 0.0
        avg_hours = round(float(agg.avg_working_hours or 0.0), 2)

        return {
            "total_active_employees": total_active,
            "total_employees": total_active,
            "checked_in_today": checked_in,
            "checked_out_today": checked_out,
            "present": checked_in,
            "absent": absent,
            "absent_today": absent,
            "late": late,
            "late_check_ins_today": late,
            "on_leave": on_leave_clamped,
            "on_leave_today": on_leave_clamped,
            "attendance_rate": rate,
            "attendance_rate_percentage": rate,
            "average_working_hours_today": avg_hours,
        }

    async def _get_total_active_employees(
        self,
        company_id: uuid.UUID,
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> int:
        """Get count of active employees for a company with optional dimension filters."""
        emp_stmt = select(func.count(Employee.id)).where(
            and_(*self._employee_filter_conditions(company_id, department_id, shift_id, location_id))
        )
        emp_res = await self.db.execute(emp_stmt)
        return int(emp_res.scalar() or 0)

    def _resolve_date_range(self, start_date: date | None, end_date: date | None, view_mode: str) -> tuple[date, date]:
        """Resolve date range with defaults based on view_mode."""
        today = date.today()
        if start_date and end_date:
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            return start_date, end_date

        if view_mode == "month":
            start = today.replace(day=1)
            if today.month == 12:
                end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            return start, end

        # Default: current week (Monday to Sunday)
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        return monday, sunday

    async def _get_holiday_dates(self, company_id: uuid.UUID, start_date: date, end_date: date) -> set[date]:
        """Fetch holiday dates from both Holiday and HolidayCalendar tables."""
        holidays: set[date] = set()
        res_h = await self.db.execute(
            select(Holiday.holiday_date).where(
                and_(
                    Holiday.holiday_date >= start_date,
                    Holiday.holiday_date <= end_date,
                    or_(Holiday.company_id == company_id, Holiday.company_id.is_(None)),
                )
            )
        )
        holidays.update(d for d in res_h.scalars().all() if d is not None)

        res_hc = await self.db.execute(
            select(HolidayCalendar.holiday_date).where(
                and_(
                    HolidayCalendar.company_id == company_id,
                    HolidayCalendar.holiday_date >= start_date,
                    HolidayCalendar.holiday_date <= end_date,
                )
            )
        )
        holidays.update(d for d in res_hc.scalars().all() if d is not None)
        return holidays

    async def _get_leave_counts_by_date(
        self,
        company_id: uuid.UUID,
        start_date: date,
        end_date: date,
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[date, int]:
        """Count distinct employees with APPROVED leaves on each day in [start_date, end_date]."""
        stmt = (
            select(LeaveRequest.employee_id, LeaveRequest.start_date, LeaveRequest.end_date)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .where(
                and_(
                    func.upper(LeaveRequest.status) == "APPROVED",
                    LeaveRequest.start_date <= end_date,
                    LeaveRequest.end_date >= start_date,
                    *self._employee_filter_conditions(company_id, department_id, shift_id, location_id),
                )
            )
        )
        rows = (await self.db.execute(stmt)).all()
        by_day: dict[date, set[uuid.UUID]] = defaultdict(set)
        for emp_id, req_start, req_end in rows:
            cur = max(start_date, req_start)
            finish = min(end_date, req_end)
            while cur <= finish:
                by_day[cur].add(emp_id)
                cur += timedelta(days=1)
        return {d: len(emp_ids) for d, emp_ids in by_day.items()}

    async def _get_daily_aggregates(
        self,
        company_id: uuid.UUID,
        start_date: date,
        end_date: date,
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get daily aggregated attendance data across [start_date, end_date] using SQL GROUP BY."""
        emp_conds = self._employee_filter_conditions(company_id, department_id, shift_id, location_id)
        stmt = (
            select(
                Attendance.date,
                func.count(Attendance.id).label("total_marked"),
                func.coalesce(
                    func.sum(case((func.lower(Attendance.status) != "absent", 1), else_=0)), 0
                ).label("present_count"),
                func.coalesce(
                    func.sum(case((func.lower(Attendance.status) == "absent", 1), else_=0)), 0
                ).label("explicit_absent"),
                func.coalesce(
                    func.sum(
                        case(
                            (or_(Attendance.is_late.is_(True), func.lower(Attendance.status) == "late"), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("late_count"),
                func.coalesce(
                    func.sum(case((func.lower(Attendance.status).in_(("half day", "half_day")), 1), else_=0)), 0
                ).label("half_day_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                or_(
                                    func.lower(Attendance.status).in_(("wfh", "remote")),
                                    func.lower(Attendance.punch_verified_by) == "remote",
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("wfh_count"),
                func.coalesce(
                    func.sum(case((Attendance.check_out_time.isnot(None), 1), else_=0)), 0
                ).label("checked_out_count"),
                func.coalesce(func.avg(Attendance.working_hours), 0.0).label("avg_working_hours"),
                func.coalesce(
                    func.sum(
                        case(
                            (Attendance.working_hours > 8.0, Attendance.working_hours - 8.0),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ).label("overtime_hours"),
            )
            .select_from(Attendance)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(
                and_(
                    Attendance.date >= start_date,
                    Attendance.date <= end_date,
                    or_(Attendance.company_id == company_id, Attendance.company_id.is_(None)),
                    *emp_conds,
                )
            )
            .group_by(Attendance.date)
            .order_by(Attendance.date)
        )
        res = await self.db.execute(stmt)
        rows = {row.date: row for row in res.all()}
        leave_counts = await self._get_leave_counts_by_date(
            company_id, start_date, end_date, department_id, shift_id, location_id
        )
        holidays = await self._get_holiday_dates(company_id, start_date, end_date)
        total_active = await self._get_total_active_employees(
            company_id, department_id, shift_id, location_id
        )

        daily_data = []
        today = date.today()
        cur = start_date
        while cur <= end_date:
            row = rows.get(cur)
            present = int(row.present_count or 0) if row else 0
            late = min(present, int(row.late_count or 0)) if row else 0
            half_day = int(row.half_day_count or 0) if row else 0
            wfh = int(row.wfh_count or 0) if row else 0
            explicit_absent = int(row.explicit_absent or 0) if row else 0
            checked_out = int(row.checked_out_count or 0) if row else 0
            avg_hours = float(row.avg_working_hours or 0.0) if row else 0.0
            overtime_hours = float(row.overtime_hours or 0.0) if row else 0.0

            raw_leave = leave_counts.get(cur, 0)
            on_leave = min(raw_leave, max(0, total_active - present)) if total_active > 0 else raw_leave

            is_weekday = cur.weekday() < 5
            is_holiday = cur in holidays
            is_future = cur > today
            countable = is_weekday and not is_holiday and not is_future

            if countable:
                absent = max(explicit_absent, max(0, total_active - present - on_leave))
            else:
                absent = explicit_absent

            daily_data.append({
                "date": cur,
                "present": present,
                "late": late,
                "half_day": half_day,
                "wfh": wfh,
                "absent": absent,
                "on_leave": on_leave,
                "checked_out": checked_out,
                "avg_working_hours": round(avg_hours, 2),
                "overtime_hours": round(overtime_hours, 2),
                "is_holiday": is_holiday,
                "is_weekend": not is_weekday,
                "is_countable": countable,
                "total": max(total_active, present + absent + on_leave),
            })
            cur += timedelta(days=1)
        return daily_data

    async def get_attendance_rate(
        self,
        company_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        view_mode: str = "week",
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        """Get attendance rate KPI & daily percentages for a date range plus prior-period delta."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        total_active = await self._get_total_active_employees(company_id, department_id, shift_id, location_id)
        daily_aggregates = await self._get_daily_aggregates(
            company_id, start_d, end_d, department_id, shift_id, location_id
        )

        period_len = max(1, (end_d - start_d).days + 1)
        prev_end = start_d - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_len - 1)
        prev_daily = await self._get_daily_aggregates(
            company_id, prev_start, prev_end, department_id, shift_id, location_id
        )

        daily = []
        present_count = 0
        late_count = 0
        absent_count = 0
        on_leave_count = 0
        expected_total = 0

        for day_data in daily_aggregates:
            d = day_data["date"]
            present = day_data["present"]
            if day_data["is_countable"] or present > 0:
                present_count += present
                late_count += day_data["late"]
                absent_count += day_data["absent"]
                on_leave_count += day_data["on_leave"]
                expected_total += total_active if day_data["is_countable"] else present
            daily.append({
                "date": d.isoformat(),
                "day": d.strftime("%a"),
                "present": present,
                "late": day_data["late"],
                "absent": day_data["absent"],
                "on_leave": day_data["on_leave"],
                "rate": round((present / total_active * 100), 2) if total_active > 0 else 0.0,
            })

        total_count = expected_total if expected_total > 0 else (present_count + absent_count + on_leave_count)
        overall_rate = round((present_count / total_count * 100), 2) if total_count > 0 else 0.0

        prev_present = sum(day["present"] for day in prev_daily if day["is_countable"] or day["present"] > 0)
        prev_expected = sum(
            (total_active if day["is_countable"] else day["present"])
            for day in prev_daily
            if day["is_countable"] or day["present"] > 0
        )
        previous_rate = round((prev_present / prev_expected * 100), 2) if prev_expected > 0 else None
        change_pp = round(overall_rate - previous_rate, 2) if previous_rate is not None else 0.0
        if previous_rate is None or abs(change_pp) < 0.01:
            trend = "stable"
        elif change_pp > 0:
            trend = "up"
        else:
            trend = "down"

        denom = total_count if total_count > 0 else 0
        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "total_active_employees": total_active,
            "overall_rate_percentage": overall_rate,
            "current_rate": overall_rate,
            "previous_rate": previous_rate,
            "change_percentage_points": change_pp,
            "trend": trend,
            "rate": overall_rate,
            "change": change_pp,
            "present_count": present_count,
            "absent_count": absent_count,
            "late_count": late_count,
            "on_leave_count": on_leave_count,
            "total_count": total_count,
            "present_percentage": round((present_count / denom) * 100, 2) if denom > 0 else 0.0,
            "absent_percentage": round((absent_count / denom) * 100, 2) if denom > 0 else 0.0,
            "late_percentage": round((late_count / denom) * 100, 2) if denom > 0 else 0.0,
            "leave_percentage": round((on_leave_count / denom) * 100, 2) if denom > 0 else 0.0,
            "period": {"start": start_d.isoformat(), "end": end_d.isoformat()},
            "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
            "daily": daily,
        }

    async def get_attendance_distribution(
        self,
        company_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        view_mode: str = "week",
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        """Get attendance distribution (on time, late, absent, on leave) for a date range."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        daily_aggregates = await self._get_daily_aggregates(
            company_id, start_d, end_d, department_id, shift_id, location_id
        )

        total_on_time = 0
        total_late = 0
        total_absent = 0
        total_on_leave = 0
        total_half_day = 0
        total_wfh = 0

        for day_data in daily_aggregates:
            present = day_data["present"]
            late = day_data["late"]
            on_time = max(0, present - late)
            total_on_time += on_time
            total_late += late
            total_absent += day_data["absent"]
            total_on_leave += day_data["on_leave"]
            total_half_day += day_data["half_day"]
            total_wfh += day_data["wfh"]

        total = total_on_time + total_late + total_absent + total_on_leave

        def pct(val: int) -> float:
            return round((val / total * 100), 2) if total > 0 else 0.0

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "present": total_on_time,
            "on_time": total_on_time,
            "late": total_late,
            "absent": total_absent,
            "on_leave": total_on_leave,
            "onLeave": total_on_leave,
            "half_day": total_half_day,
            "wfh": total_wfh,
            "total": total,
            "distribution": [
                {"label": "On Time", "key": "on_time", "count": total_on_time, "percentage": pct(total_on_time)},
                {"label": "Late", "key": "late", "count": total_late, "percentage": pct(total_late)},
                {"label": "Absent", "key": "absent", "count": total_absent, "percentage": pct(total_absent)},
                {"label": "On Leave", "key": "on_leave", "count": total_on_leave, "percentage": pct(total_on_leave)},
            ],
        }

    async def get_attendance_weekly(
        self,
        company_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        view_mode: str = "week",
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        """Get weekly aggregated attendance by weekday (Mon-Sun)."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        daily_aggregates = await self._get_daily_aggregates(
            company_id, start_d, end_d, department_id, shift_id, location_id
        )

        weekday_map = defaultdict(
            lambda: {
                "present": 0,
                "late": 0,
                "absent": 0,
                "on_leave": 0,
                "hours": 0.0,
                "overtime_hours": 0.0,
            }
        )
        for day_data in daily_aggregates:
            wd = day_data["date"].weekday()
            present = day_data["present"]
            weekday_map[wd]["present"] += present
            weekday_map[wd]["late"] += day_data["late"]
            weekday_map[wd]["absent"] += day_data["absent"]
            weekday_map[wd]["on_leave"] += day_data["on_leave"]
            weekday_map[wd]["hours"] += day_data["avg_working_hours"] * present if present > 0 else 0.0
            weekday_map[wd]["overtime_hours"] += day_data["overtime_hours"]

        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        weekly = []
        for i in range(7):
            data = weekday_map[i]
            present = data["present"]
            avg_hours = round(data["hours"] / present, 2) if present > 0 else 0.0
            item_total = present + data["absent"] + data["on_leave"]
            weekly.append({
                "day": day_labels[i],
                "present": present,
                "late": data["late"],
                "absent": data["absent"],
                "on_leave": data["on_leave"],
                "onLeave": data["on_leave"],
                "total": item_total,
                "average_working_hours": avg_hours,
                "overtime_hours": round(data["overtime_hours"], 2),
            })

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "weekly": weekly,
            "data": weekly,
        }

    async def get_attendance_trends(
        self,
        company_id: uuid.UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        view_mode: str = "week",
        department_id: str | None = None,
        shift_id: str | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        """Get daily attendance trends for a date range."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        total_active = await self._get_total_active_employees(company_id, department_id, shift_id, location_id)
        daily_aggregates = await self._get_daily_aggregates(
            company_id, start_d, end_d, department_id, shift_id, location_id
        )

        trends = []
        for day_data in daily_aggregates:
            d = day_data["date"]
            present = day_data["present"]
            rate = round((present / total_active * 100), 2) if total_active > 0 else 0.0
            trends.append({
                "date": d.isoformat(),
                "day": d.strftime("%a"),
                "present": present,
                "late": day_data["late"],
                "absent": day_data["absent"],
                "on_leave": day_data["on_leave"],
                "onLeave": day_data["on_leave"],
                "half_day": day_data["half_day"],
                "wfh": day_data["wfh"],
                "checked_out": day_data["checked_out"],
                "total": day_data["total"],
                "attendance_rate": rate,
                "average_working_hours": day_data["avg_working_hours"],
                "overtime_hours": day_data["overtime_hours"],
            })

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "total_active_employees": total_active,
            "trends": trends,
            "data": trends,
        }