"""Leave Support AI Agent.

Handles:
- Fetching leave balance per leave type (Sick Leave, Casual Leave, Vacation Leave) via LeaveService.
- Applying leave by creating a PENDING LeaveRequest via LeaveService.
- Canceling leave requests via LeaveService.
- Listing upcoming holidays (from holiday_calendar table or default calendar).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.models.calendar import HolidayCalendar
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.schemas.leave import LeaveRequestCreate
from app.services.leave_service import LeaveService

logger = logging.getLogger(__name__)


def _normalize_leave_type(raw_type: str) -> str:
    cleaned = raw_type.strip()
    lowered = cleaned.lower()
    if "sick" in lowered:
        return "Sick Leave"
    if "casual" in lowered:
        return "Casual Leave"
    if "vacation" in lowered or "privilege" in lowered or "annual" in lowered:
        return "Vacation Leave"
    return cleaned


class LeaveAgent:
    """Specialized agent handling leave balances, applications, and holiday inquiries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_leave_balances(self, employee_id: uuid.UUID) -> dict[str, Any]:
        """Fetch leave type balances (allocated, used, remaining) using LeaveService."""
        service = LeaveService(self.db)
        bals = await service.get_leave_balances(employee_id)
        balances: dict[str, Any] = {}
        for b in bals:
            key = b.leave_type.upper().replace(" ", "_")
            balances[key] = {
                "allocated": float(b.total_days),
                "used": float(b.used_days),
                "remaining": float(b.remaining_days),
            }
        return balances

    async def apply_leave(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Submit leave request via LeaveService (creates a PENDING request, goes through approval)."""
        ltype = _normalize_leave_type(leave_type)
        days = (end_date - start_date).days + 1
        if days <= 0:
            return {"success": False, "error": "End date must be on or after start date."}

        try:
            service = LeaveService(self.db)
            data = LeaveRequestCreate(
                leave_type=ltype,
                start_date=start_date,
                end_date=end_date,
                reason="Applied via AI Support Agent",
            )
            leave = await service.apply_leave(employee_id, data, role="employee")

            policy = await service.repo.get_employee_leave_policy_by_type(employee_id, ltype)
            used_days = float(policy.used_days) if policy else 0.0

            return {
                "success": True,
                "message": f"Successfully applied {float(leave.total_days)} day(s) of {ltype} from {start_date} to {end_date} (Pending approval).",
                "days_applied": float(leave.total_days),
                "new_used_days": used_days,
            }
        except (BadRequestException, NotFoundException, AppException) as exc:
            return {"success": False, "error": exc.message}
        except Exception as exc:
            logger.exception("AI agent apply_leave failed", exc_info=exc)
            return {"success": False, "error": str(exc)}

    async def cancel_leave(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        days: float = 1.0,
        leave_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Cancel leave request via LeaveService."""
        ltype = _normalize_leave_type(leave_type)
        try:
            service = LeaveService(self.db)
            emp = await self.db.get(Employee, employee_id)
            if not emp:
                return {"success": False, "error": "Employee not found."}

            target_leave: LeaveRequest | None = None
            if leave_id:
                target_leave = await service.repo.get_leave_by_id(leave_id)
            else:
                stmt = (
                    select(LeaveRequest)
                    .where(
                        LeaveRequest.employee_id == employee_id,
                        LeaveRequest.leave_type == ltype,
                        LeaveRequest.status.in_(["PENDING", "APPROVED"]),
                    )
                    .order_by(LeaveRequest.created_at.desc())
                    .limit(1)
                )
                res = await self.db.execute(stmt)
                target_leave = res.scalars().first()

            if not target_leave:
                return {"success": False, "error": f"No active leave found for {ltype}."}

            prev_status = target_leave.status
            cancelled = await service.cancel_leave(
                leave_id=target_leave.id,
                caller_user_id=emp.user_id if emp.user_id else uuid.uuid4(),
                caller_role="employee",
                caller_company_id=emp.company_id if emp.company_id else uuid.uuid4(),
            )

            policy = await service.repo.get_employee_leave_policy_by_type(employee_id, ltype)
            new_used = float(policy.used_days) if policy else 0.0

            return {
                "success": True,
                "message": f"Successfully canceled {float(cancelled.total_days)} day(s) of {ltype} leave.",
                "refunded_days": float(cancelled.total_days) if prev_status == "APPROVED" else 0.0,
                "new_used": new_used,
            }
        except (BadRequestException, NotFoundException, AppException) as exc:
            return {"success": False, "error": exc.message}
        except Exception as exc:
            logger.exception("AI agent cancel_leave failed", exc_info=exc)
            return {"success": False, "error": str(exc)}

    async def get_upcoming_holidays(self) -> list[dict[str, Any]]:
        """Fetch holiday lists from calendar module."""
        stmt = select(HolidayCalendar).order_by(HolidayCalendar.holiday_date.asc())
        res = await self.db.execute(stmt)
        holidays = res.scalars().all()

        results = []
        for h in holidays:
            results.append({
                "date": h.holiday_date.isoformat(),
                "name": h.holiday_name,
                "day_of_week": h.holiday_date.strftime("%A"),
            })

        # Fallback default calendar
        if not results:
            results = [
                {"date": "2026-01-01", "name": "New Year's Day", "day_of_week": "Thursday"},
                {"date": "2026-01-26", "name": "Republic Day", "day_of_week": "Monday"},
                {"date": "2026-08-15", "name": "Independence Day", "day_of_week": "Saturday"},
                {"date": "2026-10-02", "name": "Gandhi Jayanti", "day_of_week": "Friday"},
                {"date": "2026-12-25", "name": "Christmas Day", "day_of_week": "Friday"},
            ]

        return results
