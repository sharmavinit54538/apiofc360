"""Enterprise Break Tracking Service for Face Attendance.

Enforces business rules:
- Cannot start break without active check-in
- Cannot start two breaks simultaneously
- Cannot end a break that is not active
- Cannot start/end break after checking out
- Automatically calculates session duration and total aggregated break hours
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance
from app.attendance.models.attendance_break import AttendanceBreak
from app.attendance.repositories.attendance_repository import AttendanceRepository
from app.attendance.utils.helpers import write_audit_log
from app.models.employee import Employee

logger = logging.getLogger(__name__)


class BreakService:
    """Handles break session lifecycle (start, end, and duration tracking)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AttendanceRepository(db)

    async def start_break(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        notes: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AttendanceBreak:
        """Starts a new break session for the authenticated employee."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "EMPLOYEE_NOT_FOUND", "message": "Employee profile not found."},
            )

        today = date.today()
        record = await self.repo.get_record_by_date(employee.id, today)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_ACTIVE_CHECKIN", "message": "Cannot start break without checking in today first."},
            )

        if record.check_out_time is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "ALREADY_CHECKED_OUT", "message": "Cannot take a break after checking out for the day."},
            )

        # Check if already on an active break
        active_break = await self.get_active_break_for_attendance(record.id)
        if active_break:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "BREAK_ACTIVE",
                    "message": "A break session is already active. Please end your current break first.",
                },
            )

        now = datetime.now(timezone.utc)
        break_session = AttendanceBreak(
            id=uuid.uuid4(),
            attendance_id=record.id,
            employee_id=employee.id,
            company_id=company_id,
            break_start=now,
            break_end=None,
            duration_minutes=None,
            status="ACTIVE",
            notes=notes,
        )
        self.db.add(break_session)

        # Audit log
        details = f"Break Started: Time={now.isoformat()} | Notes={notes or 'None'}"
        await write_audit_log(self.db, user_id, "BREAK_START", ip_address, details, company_id=company_id)

        await self.db.commit()
        await self.db.refresh(break_session)
        return break_session

    async def end_break(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        ip_address: Optional[str] = None,
    ) -> AttendanceBreak:
        """Ends the currently active break session and recalculates total break duration."""
        employee = await self.repo.get_employee_by_user_id(user_id)
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "EMPLOYEE_NOT_FOUND", "message": "Employee profile not found."},
            )

        today = date.today()
        record = await self.repo.get_record_by_date(employee.id, today)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_ACTIVE_CHECKIN", "message": "No active attendance session found."},
            )

        active_break = await self.get_active_break_for_attendance(record.id)
        if not active_break:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_ACTIVE_BREAK", "message": "No active break session found to end."},
            )

        now = datetime.now(timezone.utc)
        delta = now - active_break.break_start
        duration_minutes = round(max(0.0, delta.total_seconds() / 60.0), 2)

        active_break.break_end = now
        active_break.duration_minutes = duration_minutes
        active_break.status = "COMPLETED"

        # Recompute total aggregated break duration in hours for attendance record
        all_breaks = await self.get_all_breaks_for_attendance(record.id)
        total_mins = sum(b.duration_minutes or 0.0 for b in all_breaks if b.id != active_break.id) + duration_minutes
        record.break_duration = round(total_mins / 60.0, 2)

        # Audit log
        details = f"Break Ended: Duration={duration_minutes} mins | TotalBreakHrs={record.break_duration}"
        await write_audit_log(self.db, user_id, "BREAK_END", ip_address, details, company_id=company_id)

        await self.db.commit()
        await self.db.refresh(active_break)
        return active_break

    async def get_active_break_for_attendance(self, attendance_id: uuid.UUID) -> Optional[AttendanceBreak]:
        """Finds any active break for the attendance record."""
        stmt = select(AttendanceBreak).where(
            and_(
                AttendanceBreak.attendance_id == attendance_id,
                AttendanceBreak.status == "ACTIVE",
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_all_breaks_for_attendance(self, attendance_id: uuid.UUID) -> List[AttendanceBreak]:
        """Retrieves all break sessions for an attendance record."""
        stmt = (
            select(AttendanceBreak)
            .where(AttendanceBreak.attendance_id == attendance_id)
            .order_by(AttendanceBreak.break_start.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_break_summary(self, attendance_id: uuid.UUID) -> Dict[str, Any]:
        """Returns structured break status summary for an attendance record."""
        breaks = await self.get_all_breaks_for_attendance(attendance_id)
        active_break = next((b for b in breaks if b.status == "ACTIVE"), None)

        total_mins = sum(b.duration_minutes or 0.0 for b in breaks if b.duration_minutes is not None)
        if active_break:
            current_elapsed = (datetime.now(timezone.utc) - active_break.break_start).total_seconds() / 60.0
            total_mins += max(0.0, current_elapsed)

        return {
            "is_on_break": active_break is not None,
            "current_break": {
                "id": str(active_break.id),
                "break_start": active_break.break_start.isoformat(),
                "notes": active_break.notes,
            } if active_break else None,
            "total_break_minutes": round(total_mins, 1),
            "total_break_hours": round(total_mins / 60.0, 2),
            "break_sessions_count": len(breaks),
            "breaks": [
                {
                    "id": str(b.id),
                    "break_start": b.break_start.isoformat(),
                    "break_end": b.break_end.isoformat() if b.break_end else None,
                    "duration_minutes": b.duration_minutes,
                    "status": b.status,
                    "notes": b.notes,
                }
                for b in breaks
            ],
        }
