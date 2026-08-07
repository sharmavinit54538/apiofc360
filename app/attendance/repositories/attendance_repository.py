"""Database repository for daily Face Attendance session checks."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee


class AttendanceRepository:
    """Encapsulates session check database operations for Daily Face Attendance."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_session(self, employee_id: uuid.UUID) -> Optional[Attendance]:
        """Finds any check-in record without a checkout timestamp."""
        stmt = select(Attendance).where(
            and_(Attendance.employee_id == employee_id, Attendance.check_out_time == None)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_record_by_date(self, employee_id: uuid.UUID, dt: date) -> Optional[Attendance]:
        """Finds attendance record for a specific employee on a specific date."""
        stmt = select(Attendance).where(
            and_(Attendance.employee_id == employee_id, Attendance.date == dt)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_employee_by_user_id(self, user_id: uuid.UUID) -> Optional[Employee]:
        """Finds employee profile linked to user account ID."""
        stmt = select(Employee).where(
            and_(Employee.user_id == user_id, Employee.is_deleted == False)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

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
