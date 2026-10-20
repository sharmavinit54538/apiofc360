"""Daily Face Attendance analytics service."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee


class AttendanceAnalyticsService:
    """Calculates attendance dashboard KPIs and overview trends."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_company_analytics(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Fetch today's statistics, checked-in count, absent count, and presence rates."""
        # 1. Total Active Employees
        emp_stmt = select(func.count(Employee.id)).where(
            and_(Employee.company_id == company_id, Employee.is_deleted == False, Employee.status == "ACTIVE")
        )
        emp_res = await self.db.execute(emp_stmt)
        total_active = emp_res.scalar() or 0

        # 2. Today's logs
        today = date.today()
        att_stmt = select(Attendance).where(
            and_(Attendance.company_id == company_id, Attendance.date == today)
        )
        att_res = await self.db.execute(att_stmt)
        today_records = att_res.scalars().all()

        checked_in = len(today_records)
        checked_out = sum(1 for r in today_records if r.check_out_time is not None)
        absent = max(0, total_active - checked_in)

        # 3. Present Percentage Rate
        rate = round((checked_in / total_active) * 100.0, 2) if total_active > 0 else 0.0

        # 4. Average working hours
        hours = [r.working_hours for r in today_records if r.working_hours is not None]
        avg_hours = round(sum(hours) / len(hours), 2) if hours else 0.0

        # 5. Late Check-ins based on assigned shift engine
        late = sum(
            1 for r in today_records
            if r.is_late is True or (r.is_late is None and r.check_in_time and (r.check_in_time.hour > 9 or (r.check_in_time.hour == 9 and r.check_in_time.minute > 30)))
        )

        return {
            "total_active_employees": total_active,
            "checked_in_today": checked_in,
            "checked_out_today": checked_out,
            "absent_today": absent,
            "attendance_rate_percentage": rate,
            "average_working_hours_today": avg_hours,
            "late_check_ins_today": late,
        }

    async def _get_total_active_employees(self, company_id: uuid.UUID) -> int:
        """Get count of active employees for a company."""
        emp_stmt = select(func.count(Employee.id)).where(
            and_(Employee.company_id == company_id, Employee.is_deleted == False, Employee.status == "ACTIVE")
        )
        emp_res = await self.db.execute(emp_stmt)
        return emp_res.scalar() or 0

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

    async def _get_daily_aggregates(
        self, company_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Get daily aggregated attendance data using SQL GROUP BY."""
        stmt = (
            select(
                Attendance.date,
                func.count(Attendance.id).label("total"),
                func.sum(func.cast(Attendance.is_late, int)).label("late_count"),
                func.sum(func.case((Attendance.check_out_time.isnot(None), 1), else_=0)).label("checked_out_count"),
                func.avg(Attendance.working_hours).label("avg_working_hours"),
            )
            .select_from(Attendance)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(
                and_(
                    Attendance.date >= start_date,
                    Attendance.date <= end_date,
                    (Attendance.company_id == company_id) | (Employee.company_id == company_id),
                )
            )
            .group_by(Attendance.date)
            .order_by(Attendance.date)
        )
        res = await self.db.execute(stmt)
        rows = res.all()

        daily_data = []
        for row in rows:
            daily_data.append({
                "date": row.date,
                "present": row.total,
                "late": row.late_count or 0,
                "checked_out": row.checked_out_count or 0,
                "avg_working_hours": float(row.avg_working_hours) if row.avg_working_hours else 0.0,
            })
        return daily_data

    async def get_attendance_rate(
        self, company_id: uuid.UUID, start_date: date | None = None, end_date: date | None = None, view_mode: str = "week"
    ) -> dict[str, Any]:
        """Get attendance rate analytics for a date range."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        total_active = await self._get_total_active_employees(company_id)

        daily_aggregates = await self._get_daily_aggregates(company_id, start_d, end_d)

        daily = []
        total_present_countable = 0
        countable_days = 0

        for day_data in daily_aggregates:
            d = day_data["date"]
            present = day_data["present"]
            is_weekday = d.weekday() < 5  # Monday=0 to Friday=4
            is_future = d > date.today()
            countable = is_weekday and not is_future

            if countable:
                countable_days += 1
                total_present_countable += present

            daily.append({
                "date": d.isoformat(),
                "day": d.strftime("%a"),
                "present": present,
                "rate": round((present / total_active * 100), 2) if total_active > 0 else 0.0,
            })

        overall_rate = round(
            (total_present_countable / (total_active * countable_days) * 100), 2
        ) if total_active > 0 and countable_days > 0 else 0.0

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "total_active_employees": total_active,
            "overall_rate_percentage": overall_rate,
            "daily": daily,
        }

    async def get_attendance_distribution(
        self, company_id: uuid.UUID, start_date: date | None = None, end_date: date | None = None, view_mode: str = "week"
    ) -> dict[str, Any]:
        """Get attendance distribution (on time, late, absent) for a date range."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        total_active = await self._get_total_active_employees(company_id)

        daily_aggregates = await self._get_daily_aggregates(company_id, start_d, end_d)

        total_on_time = 0
        total_late = 0
        total_absent = 0

        for day_data in daily_aggregates:
            d = day_data["date"]
            present = day_data["present"]
            late = day_data["late"]
            is_weekday = d.weekday() < 5
            is_future = d > date.today()
            countable = is_weekday and not is_future

            on_time = max(0, present - late)
            absent = max(0, total_active - present) if countable else 0

            total_on_time += on_time
            total_late += late
            total_absent += absent

        total = total_on_time + total_late + total_absent

        def pct(val: int) -> float:
            return round((val / total * 100), 2) if total > 0 else 0.0

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "total": total,
            "distribution": [
                {"label": "On Time", "key": "on_time", "count": total_on_time, "percentage": pct(total_on_time)},
                {"label": "Late", "key": "late", "count": total_late, "percentage": pct(total_late)},
                {"label": "Absent", "key": "absent", "count": total_absent, "percentage": pct(total_absent)},
            ],
        }

    async def get_attendance_weekly(
        self, company_id: uuid.UUID, start_date: date | None = None, end_date: date | None = None, view_mode: str = "week"
    ) -> dict[str, Any]:
        """Get weekly aggregated attendance by weekday (Mon-Sun)."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)

        daily_aggregates = await self._get_daily_aggregates(company_id, start_d, end_d)
        total_active = await self._get_total_active_employees(company_id)

        # Aggregate by weekday (0=Mon ... 6=Sun)
        weekday_map = defaultdict(lambda: {"present": 0, "late": 0, "absent": 0, "hours": 0.0, "days_count": 0})
        for day_data in daily_aggregates:
            d = day_data["date"]
            wd = d.weekday()
            is_weekday = wd < 5
            is_future = d > date.today()
            countable = is_weekday and not is_future

            present = day_data["present"]
            late = day_data["late"]
            absent = max(0, total_active - present) if countable else 0

            weekday_map[wd]["present"] += present
            weekday_map[wd]["late"] += late
            weekday_map[wd]["absent"] += absent
            weekday_map[wd]["hours"] += day_data["avg_working_hours"] * present if present > 0 else 0.0
            weekday_map[wd]["days_count"] += 1 if countable else 0

        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        weekly = []
        for i in range(7):
            data = weekday_map[i]
            present = data["present"]
            days = data["days_count"]
            avg_hours = round(data["hours"] / present, 2) if present > 0 else 0.0
            weekly.append({
                "day": day_labels[i],
                "present": present,
                "late": data["late"],
                "absent": data["absent"],
                "average_working_hours": avg_hours,
            })

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "weekly": weekly,
        }

    async def get_attendance_trends(
        self, company_id: uuid.UUID, start_date: date | None = None, end_date: date | None = None, view_mode: str = "week"
    ) -> dict[str, Any]:
        """Get daily attendance trends for a date range."""
        start_d, end_d = self._resolve_date_range(start_date, end_date, view_mode)
        total_active = await self._get_total_active_employees(company_id)

        daily_aggregates = await self._get_daily_aggregates(company_id, start_d, end_d)

        trends = []
        for day_data in daily_aggregates:
            d = day_data["date"]
            present = day_data["present"]
            late = day_data["late"]
            is_weekday = d.weekday() < 5
            is_future = d > date.today()
            countable = is_weekday and not is_future

            absent = max(0, total_active - present) if countable else 0
            checked_out = day_data["checked_out"]
            rate = round((present / total_active * 100), 2) if total_active > 0 else 0.0
            avg_hours = day_data["avg_working_hours"]

            trends.append({
                "date": d.isoformat(),
                "day": d.strftime("%a"),
                "present": present,
                "late": late,
                "absent": absent,
                "checked_out": checked_out,
                "attendance_rate": rate,
                "average_working_hours": round(avg_hours, 2),
            })

        return {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "view_mode": view_mode,
            "total_active_employees": total_active,
            "trends": trends,
        }