"""Daily Face Attendance log history and current status service."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.repositories.history_repository import AttendanceHistoryRepository
from app.attendance.schemas.response import AttendanceResponse
from app.attendance.services.break_service import BreakService
from app.attendance.services.shift_service import ShiftService
from app.core.exceptions import AppException


class AttendanceHistoryService:
    """Handles retrieval of daily check-in logs and real-time punch state."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)
        self.history_repo = AttendanceHistoryRepository(db)
        self.shift_service = ShiftService(db)
        self.break_service = BreakService(db)

    async def get_today_attendance(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Determines full current attendance and break state for the employee."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        if not employee:
            raise AppException("Employee record not found.", status_code=404)

        today = date.today()
        # Resolve shift information
        shift_info = await self.shift_service.resolve_employee_shift(employee, today)
        is_enrolled = bool(getattr(employee, "is_face_enrolled", False) and getattr(employee, "face_embedding", None))
        enrolled_at = getattr(employee, "face_enrolled_at", None)

        record = await self.repo.get_record_by_date(employee.id, today)

        emp_summary = {
            "id": employee.id,
            "employee_id": employee.employee_id,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "department": employee.department,
            "designation": employee.designation,
            "branch": employee.branch,
            "work_location": employee.work_location,
        }

        shift_summary = {
            "shift_id": str(shift_info.get("shift_id")) if shift_info.get("shift_id") else None,
            "shift_name": shift_info.get("shift_name"),
            "start_time": shift_info["start_time"].strftime("%H:%M") if shift_info.get("start_time") else None,
            "end_time": shift_info["end_time"].strftime("%H:%M") if shift_info.get("end_time") else None,
            "grace_period_mins": shift_info.get("grace_period_mins"),
            "is_overnight": shift_info.get("is_overnight", False),
            "is_off": shift_info.get("is_off", False),
            "is_holiday": shift_info.get("is_holiday", False),
            "holiday_name": shift_info.get("holiday_name"),
        }

        if not record:
            return {
                "checked_in": False,
                "checked_out": False,
                "check_in_time": None,
                "check_out_time": None,
                "working_hours": None,
                "break_duration_hours": 0.0,
                "total_break_minutes": 0.0,
                "is_on_break": False,
                "current_break": None,
                "breaks": [],
                "is_late": False,
                "late_minutes": 0,
                "shift": shift_summary,
                "is_face_enrolled": is_enrolled,
                "face_enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
                "verification_status": getattr(employee, "verification_status", "ACTIVE"),
                "employee": emp_summary,
                "today_attendance": None,
                "message": "You have not checked in yet today.",
            }

        # Check break details
        break_summary = await self.break_service.get_break_summary(record.id)

        checked_out = record.check_out_time is not None
        msg = f"Checked in at {record.check_in_time.strftime('%I:%M %p')}."
        if checked_out and record.check_out_time:
            msg += f" Checked out at {record.check_out_time.strftime('%I:%M %p')}."

        record.employee_name = f"{employee.first_name} {employee.last_name}"
        today_att_serialized = AttendanceResponse.model_validate(record)

        return {
            "checked_in": True,
            "checked_out": checked_out,
            "check_in_time": record.check_in_time,
            "check_out_time": record.check_out_time,
            "working_hours": record.working_hours,
            "break_duration_hours": break_summary.get("total_break_hours", 0.0),
            "total_break_minutes": break_summary.get("total_break_minutes", 0.0),
            "is_on_break": break_summary.get("is_on_break", False),
            "current_break": break_summary.get("current_break"),
            "breaks": break_summary.get("breaks", []),
            "is_late": record.is_late or False,
            "late_minutes": record.late_minutes or 0,
            "shift": shift_summary,
            "is_face_enrolled": is_enrolled,
            "face_enrolled_at": enrolled_at.isoformat() if enrolled_at else None,
            "verification_status": getattr(employee, "verification_status", "ACTIVE"),
            "employee": emp_summary,
            "today_attendance": today_att_serialized,
            "message": msg,
        }

    async def get_own_history(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        limit: int = 20,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[List[Attendance], int]:
        """Fetches historical check-in logs for current employee with date filtering."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        if not employee:
            return [], 0
        items, total = await self.history_repo.get_own_history(
            employee.id, page=page, limit=limit, start_date=start_date, end_date=end_date
        )
        for item in items:
            item.employee_name = f"{employee.first_name} {employee.last_name}"
        return items, total

    async def get_team_attendance(
        self,
        manager_user_id: uuid.UUID,
        company_id: uuid.UUID,
        page: int = 1,
        limit: int = 20,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[List[Attendance], int]:
        """Fetches check-in logs for direct reporting team members."""
        manager = await self.repo.get_employee_by_user_id(manager_user_id)
        if not manager:
            raise AppException("Manager employee record not found.", status_code=404)

        team = await self.repo.get_team_reporting_employees(manager.id, company_id)
        team_ids = [emp.id for emp in team]
        if not team_ids:
            return [], 0

        emp_map = {emp.id: f"{emp.first_name} {emp.last_name}" for emp in team}
        items, total = await self.history_repo.get_team_history(
            team_ids, page=page, limit=limit, start_date=start_date, end_date=end_date
        )
        for item in items:
            item.employee_name = emp_map.get(item.employee_id, "Unknown Employee")
        return items, total

    async def get_company_attendance(
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
        """Fetches check-in logs across the entire company with comprehensive filters."""
        effective_dept = department or dept
        items, total = await self.history_repo.get_company_history(
            company_id=company_id,
            branch=branch,
            department=effective_dept,
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            limit=limit,
        )
        for item in items:
            if item.employee:
                item.employee_name = f"{item.employee.first_name} {item.employee.last_name}"
            else:
                item.employee_name = "Unknown Employee"
        return items, total
