"""Database repository for daily Face Attendance log history queries."""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.models.attendance import Attendance
from app.models.employee import Employee


class AttendanceHistoryRepository:
    """Queries for daily attendance records history."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_own_history(
        self,
        employee_id: uuid.UUID,
        page: int = 1,
        limit: int = 20,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[List[Attendance], int]:
        """Fetches paginated logs for a single employee with date range filtering."""
        conditions = [Attendance.employee_id == employee_id]
        if start_date:
            conditions.append(Attendance.date >= start_date)
        if end_date:
            conditions.append(Attendance.date <= end_date)

        count_stmt = select(func.count(Attendance.id)).where(and_(*conditions))
        count_res = await self.db.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = (
            select(Attendance)
            .where(and_(*conditions))
            .order_by(Attendance.date.desc(), Attendance.check_in_time.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def get_team_history(
        self,
        emp_ids: List[uuid.UUID],
        page: int = 1,
        limit: int = 20,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[List[Attendance], int]:
        """Fetches paginated logs for a list of employee IDs with date range filtering."""
        conditions = [Attendance.employee_id.in_(emp_ids)]
        if start_date:
            conditions.append(Attendance.date >= start_date)
        if end_date:
            conditions.append(Attendance.date <= end_date)

        count_stmt = select(func.count(Attendance.id)).where(and_(*conditions))
        count_res = await self.db.execute(count_stmt)
        total = count_res.scalar() or 0

        stmt = (
            select(Attendance)
            .where(and_(*conditions))
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
        employee_id: Optional[uuid.UUID] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[Attendance], int]:
        """Fetches paginated company-wide logs with branch, department, employee, and date filters."""
        effective_dept = department or dept
        company_filter = (Attendance.company_id == company_id) | (Employee.company_id == company_id)
        conditions = [company_filter]

        if employee_id:
            conditions.append(Attendance.employee_id == employee_id)
        if start_date:
            conditions.append(Attendance.date >= start_date)
        if end_date:
            conditions.append(Attendance.date <= end_date)

        stmt = select(Attendance).join(Employee, Attendance.employee_id == Employee.id).where(and_(*conditions))
        count_stmt = select(func.count(Attendance.id)).join(Employee, Attendance.employee_id == Employee.id).where(and_(*conditions))

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
