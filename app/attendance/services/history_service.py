"""Daily Face Attendance log history service."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.repositories.history_repository import AttendanceHistoryRepository
from app.core.exceptions import AppException


class AttendanceHistoryService:
    """Handles retrieval of daily check-in logs for employees, managers, and admins."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.history_repo = AttendanceHistoryRepository(db)

    async def get_today_attendance(self, user_id: uuid.UUID) -> dict:
        """Determines if the employee has checked in/out today."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        if not employee:
            raise AppException("Employee record not found.", status_code=404)

        record = await self.repo.get_record_by_date(employee.id, date.today())
        if not record:
            return {"checked_in": False, "checked_out": False, "message": "You have not checked in yet today."}

        checked_out = record.check_out_time is not None
        msg = f"Checked in at {record.check_in_time.strftime('%I:%M %p')}."
        if checked_out:
            msg += f" Checked out at {record.check_out_time.strftime('%I:%M %p')}."

        return {
            "checked_in": True,
            "checked_out": checked_out,
            "check_in_time": record.check_in_time,
            "check_out_time": record.check_out_time,
            "working_hours": record.working_hours,
            "message": msg,
        }

    async def get_own_history(self, user_id: uuid.UUID, page: int, limit: int) -> tuple[list[Attendance], int]:
        """Fetches historical check-in logs for currently logged-in employee."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        if not employee:
            return [], 0
        items, total = await self.history_repo.get_own_history(employee.id, page, limit)
        for item in items:
            item.employee_name = f"{employee.first_name} {employee.last_name}"
        return items, total

    async def get_team_attendance(
        self, manager_user_id: uuid.UUID, company_id: uuid.UUID, page: int, limit: int
    ) -> tuple[list[Attendance], int]:
        """Fetches check-in logs for direct reporting team members."""
        manager = await self.repo.get_employee_by_user_id(manager_user_id)
        if not manager:
            raise AppException("Manager employee record not found.", status_code=404)

        team = await self.repo.get_team_reporting_employees(manager.id, company_id)
        team_ids = [emp.id for emp in team]
        if not team_ids:
            return [], 0

        emp_map = {emp.id: f"{emp.first_name} {emp.last_name}" for emp in team}
        items, total = await self.history_repo.get_team_history(team_ids, page, limit)
        for item in items:
            item.employee_name = emp_map.get(item.employee_id, "Unknown Employee")
        return items, total

    async def get_company_attendance(
        self, company_id: uuid.UUID, branch: Optional[str] = None, dept: Optional[str] = None, page: int = 1, limit: int = 20
    ) -> tuple[list[Attendance], int]:
        """Fetches check-in logs for entire company with branch and department filters."""
        items, total = await self.history_repo.get_company_history(company_id, branch, dept, page, limit)
        for item in items:
            if item.employee:
                item.employee_name = f"{item.employee.first_name} {item.employee.last_name}"
            else:
                item.employee_name = "Unknown Employee"
        return items, total
