"""Database repository for daily Face Attendance log history queries."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee


class AttendanceHistoryRepository:
    """Queries for daily attendance records history."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_own_history(self, employee_id: uuid.UUID, page: int, limit: int) -> tuple[list[Attendance], int]:
        """Fetches paginated logs for a single employee."""
        count_stmt = select(func.count(Attendance.id)).where(Attendance.employee_id == employee_id)
        count_res = await self.db.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = (
            select(Attendance)
            .where(Attendance.employee_id == employee_id)
            .order_by(Attendance.date.desc(), Attendance.check_in_time.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def get_team_history(self, emp_ids: list[uuid.UUID], page: int, limit: int) -> tuple[list[Attendance], int]:
        """Fetches paginated logs for a list of employee IDs."""
        count_stmt = select(func.count(Attendance.id)).where(Attendance.employee_id.in_(emp_ids))
        count_res = await self.db.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = (
            select(Attendance)
            .where(Attendance.employee_id.in_(emp_ids))
            .order_by(Attendance.date.desc(), Attendance.check_in_time.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def get_company_history(
        self,
        company_id: uuid.UUID,
        branch: Optional[str] = None,
        department: Optional[str] = None,
        dept: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Attendance], int]:
        """Fetches paginated company-wide logs with branch and department filters."""
        effective_dept = department or dept
        company_filter = (Attendance.company_id == company_id) | (Employee.company_id == company_id)
        stmt = select(Attendance).join(Employee, Attendance.employee_id == Employee.id).where(company_filter)
        count_stmt = select(func.count(Attendance.id)).join(Employee, Attendance.employee_id == Employee.id).where(company_filter)

        if branch and branch.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.branch == branch)
            count_stmt = count_stmt.where(Employee.branch == branch)
        if effective_dept and effective_dept.lower() not in {"", "all"}:
            stmt = stmt.where(Employee.department == effective_dept)
            count_stmt = count_stmt.where(Employee.department == effective_dept)

        total_res = await self.db.execute(count_stmt)
        total = total_res.scalar() or 0

        stmt = (
            stmt
            .options(selectinload(Attendance.employee))
            .order_by(Attendance.date.desc(), Attendance.check_in_time.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
