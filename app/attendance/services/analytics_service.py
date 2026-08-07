"""Daily Face Attendance dashboard analytics summary service."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, and_, func
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

        # 5. Late Check-ins (check-in after 09:30 AM local/UTC time)
        late = 0
        for record in today_records:
            if record.check_in_time:
                if record.check_in_time.hour > 9 or (record.check_in_time.hour == 9 and record.check_in_time.minute > 30):
                    late += 1

        return {
            "total_active_employees": total_active,
            "checked_in_today": checked_in,
            "checked_out_today": checked_out,
            "absent_today": absent,
            "attendance_rate_percentage": rate,
            "average_working_hours_today": avg_hours,
            "late_check_ins_today": late,
        }
