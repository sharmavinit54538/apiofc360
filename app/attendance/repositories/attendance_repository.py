"""Database repository for daily Face Attendance session checks."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee


class AttendanceRepository:
    """Encapsulates session check database operations for Daily Face Attendance."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_session(self, employee_id: uuid.UUID) -> Optional[Attendance]:
        """Finds the most recent check-in record without a checkout timestamp.

        Orders by check_in_time DESC to handle legacy duplicates gracefully.
        """
        stmt = select(Attendance).where(
            and_(Attendance.employee_id == employee_id, Attendance.check_out_time.is_(None))
        ).order_by(Attendance.check_in_time.desc())
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_active_session_with_details(self, employee_id: uuid.UUID) -> Optional[dict]:
        """Finds the most recent active session and returns detailed info for frontend sync."""
        stmt = select(Attendance).where(
            and_(Attendance.employee_id == employee_id, Attendance.check_out_time.is_(None))
        ).order_by(Attendance.check_in_time.desc())
        res = await self.db.execute(stmt)
        session = res.scalars().first()
        if not session:
            return None
        return {
            "session_id": str(session.id),
            "check_in_time": session.check_in_time.isoformat() if session.check_in_time else None,
            "status": session.status,
            "date": session.date.isoformat() if session.date else None,
            "shift_name": session.shift_name,
            "is_late": session.is_late,
        }

    async def auto_close_stale_session(self, employee_id: uuid.UUID, company_tz, max_shift_hours: int = 16) -> Optional[Attendance]:
        """
        Auto-close a stale active session from a previous day or expired shift.
        
        A session is considered stale if:
        1. Its check_in_time date (in company timezone) is before today, OR
        2. The session has been active for more than max_shift_hours (default 16 hours)
        
        Returns the closed session if one was found and closed, None otherwise.
        """
        active_session = await self.get_active_session(employee_id)
        if not active_session:
            return None

        # Get company timezone to determine business date
        now_utc = datetime.now(timezone.utc)
        check_in_local = active_session.check_in_time.astimezone(company_tz) if active_session.check_in_time.tzinfo else active_session.check_in_time.replace(tzinfo=timezone.utc).astimezone(company_tz)
        today_local = now_utc.astimezone(company_tz).date()
        session_date = check_in_local.date()

        # Check if session is from a previous day
        is_previous_day = session_date < today_local
        
        # Check if session has exceeded max shift duration
        session_duration_hours = (now_utc - active_session.check_in_time).total_seconds() / 3600
        is_expired_shift = session_duration_hours > max_shift_hours

        if not is_previous_day and not is_expired_shift:
            return None  # Not stale, don't close

        # Auto-close the stale session
        auto_close_time = now_utc
        if active_session.scheduled_end:
            # Use scheduled end time if available and it's in the past
            scheduled_end_utc = active_session.scheduled_end.astimezone(timezone.utc) if active_session.scheduled_end.tzinfo else active_session.scheduled_end.replace(tzinfo=timezone.utc)
            if scheduled_end_utc < now_utc:
                auto_close_time = scheduled_end_utc

        stmt = update(Attendance).where(
            Attendance.id == active_session.id
        ).values(
            check_out_time=auto_close_time,
            status="Auto-Checked Out",
            notes=(active_session.notes or "") + f" [Auto-closed: stale session from {session_date.isoformat()}]",
            auto_closed=True,
            auto_closed_at=now_utc,
        )
        await self.db.execute(stmt)
        await self.db.flush()

        # Refresh the session to get updated values
        await self.db.refresh(active_session)
        return active_session

    async def get_record_by_date(self, employee_id: uuid.UUID, dt: date) -> Optional[Attendance]:
        """Finds attendance record for a specific employee on a specific date."""
        stmt = select(Attendance).where(
            and_(Attendance.employee_id == employee_id, Attendance.date == dt)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_employee_by_user_id(self, user_id: uuid.UUID) -> Optional[Employee]:
        """Finds employee profile linked to user account ID."""
        stmt = select(Employee).where(
            and_(Employee.user_id == user_id, Employee.is_deleted == False)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_team_reporting_employees(self, manager_id: uuid.UUID, company_id: uuid.UUID) -> list[Employee]:
        """Gets active employees reporting directly to manager."""
        stmt = select(Employee).where(
            and_(
                Employee.company_id == company_id,
                Employee.is_deleted == False,
                or_(Employee.manager_id == manager_id, Employee.reporting_manager_id == manager_id)
            )
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())