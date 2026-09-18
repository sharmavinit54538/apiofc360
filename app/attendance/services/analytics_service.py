"""Daily Face Attendance dashboard analytics summary service."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee
from app.models.company import Company


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

        # 5. Late Check-ins (check-in after 09:30 AM in company's local timezone)
        company = await self.db.get(Company, company_id)
        tz_name = (company.timezone if company and company.timezone else None) or "Asia/Kolkata"
        if not tz_name and company:
            hr_settings = getattr(company, "hr_settings", None) or {}
            if isinstance(hr_settings, dict):
                tz_name = hr_settings.get("timezone") or "Asia/Kolkata"

        try:
            target_tz = ZoneInfo(tz_name)
        except Exception:
            target_tz = ZoneInfo("Asia/Kolkata")

        late = 0
        for record in today_records:
            if record.check_in_time:
                check_in_dt = record.check_in_time
                if check_in_dt.tzinfo is None:
                    check_in_dt = check_in_dt.replace(tzinfo=timezone.utc)
                local_time = check_in_dt.astimezone(target_tz)
                if local_time.hour > 9 or (local_time.hour == 9 and local_time.minute > 30):
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
