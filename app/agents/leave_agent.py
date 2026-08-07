"""Leave Support AI Agent.

Handles:
- Fetching leave balance per leave type (CL, SL, PL) from employee_leave_policies.
- Retrieving leave history (by looking at used_days and payroll inputs).
- Applying leave (updating used_days in the database).
- Canceling leave (decrementing used_days).
- Listing upcoming holidays (from holiday_calendar table or default calendar).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.calendar import HolidayCalendar

logger = logging.getLogger(__name__)


class LeaveAgent:
    """Specialized agent handling leave balances, applications, and holiday inquiries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_leave_balances(self, employee_id: uuid.UUID) -> dict[str, Any]:
        """Fetch leave type balances (allocated, used, remaining)."""
        stmt = select(EmployeeLeavePolicy).where(EmployeeLeavePolicy.employee_id == employee_id)
        res = await self.db.execute(stmt)
        policies = res.scalars().all()

        balances = {}
        for p in policies:
            remaining = p.total_days - p.used_days
            balances[p.leave_type.upper()] = {
                "allocated": float(p.total_days),
                "used": float(p.used_days),
                "remaining": float(remaining),
            }

        # If empty, return standard defaults
        if not balances:
            balances = {
                "CASUAL_LEAVE": {"allocated": 12.0, "used": 0.0, "remaining": 12.0},
                "SICK_LEAVE": {"allocated": 12.0, "used": 0.0, "remaining": 12.0},
                "PRIVILEGE_LEAVE": {"allocated": 15.0, "used": 0.0, "remaining": 15.0},
            }

        return balances

    async def apply_leave(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Deduct leave balance and return success response."""
        ltype = leave_type.upper().replace(" ", "_")
        
        # Calculate days
        days = (end_date - start_date).days + 1
        if days <= 0:
            return {"success": False, "error": "End date must be on or after start date."}

        stmt = select(EmployeeLeavePolicy).where(
            EmployeeLeavePolicy.employee_id == employee_id,
            EmployeeLeavePolicy.leave_type == ltype
        )
        res = await self.db.execute(stmt)
        policy = res.scalar_one_or_none()

        if not policy:
            # Create a policy on the fly to support new employees
            policy = EmployeeLeavePolicy(
                employee_id=employee_id,
                leave_type=ltype,
                total_days=Decimal("15.0"),
                used_days=Decimal("0.0"),
            )
            self.db.add(policy)
            await self.db.flush()

        remaining = policy.total_days - policy.used_days
        if remaining < days:
            return {
                "success": False,
                "error": f"Insufficient leave balance. Remaining: {remaining} days, requested: {days} days."
            }

        # Deduct balance
        policy.used_days += Decimal(str(days))
        await self.db.commit()

        return {
            "success": True,
            "message": f"Successfully applied {days} day(s) of {ltype} from {start_date} to {end_date}.",
            "days_applied": days,
            "new_used_days": float(policy.used_days),
        }

    async def cancel_leave(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        days: float,
    ) -> dict[str, Any]:
        """Credit back leave balance."""
        ltype = leave_type.upper().replace(" ", "_")
        
        stmt = select(EmployeeLeavePolicy).where(
            EmployeeLeavePolicy.employee_id == employee_id,
            EmployeeLeavePolicy.leave_type == ltype
        )
        res = await self.db.execute(stmt)
        policy = res.scalar_one_or_none()

        if not policy:
            return {"success": False, "error": f"No active leave policy found for {ltype}."}

        if float(policy.used_days) < days:
            days = float(policy.used_days)

        policy.used_days -= Decimal(str(days))
        await self.db.commit()

        return {
            "success": True,
            "message": f"Successfully canceled {days} day(s) of {ltype} leave.",
            "refunded_days": days,
            "new_used": float(policy.used_days),
        }

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
