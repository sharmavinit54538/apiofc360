"""Roster Service - manages shift plan entries for rosters."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.utils.time_parse import InvalidTimeFormatError, parse_time_str
from app.models.employee import Employee
from app.models.shift import Shift
from app.models.shift_plan import EntryApprovalStatus, ShiftPlan, ShiftPlanEntry, ShiftType

logger = logging.getLogger(__name__)


class RosterService:
    """Service for roster management (backed by ShiftPlanEntry)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_or_create_manual_plan(
        self, company_id: uuid.UUID, period_start: date, period_end: date
    ) -> ShiftPlan:
        """Get or create the MANUAL plan for a company/month."""
        # Find existing MANUAL plan for this period
        stmt = select(ShiftPlan).where(
            and_(
                ShiftPlan.company_id == company_id,
                ShiftPlan.source == "MANUAL",
                ShiftPlan.period_start <= period_end,
                ShiftPlan.period_end >= period_start,
            )
        )
        result = await self.db.execute(stmt)
        plan = result.scalars().first()

        if plan:
            return plan

        # Create new MANUAL plan
        plan = ShiftPlan(
            company_id=company_id,
            plan_type="MONTHLY",
            period_start=period_start,
            period_end=period_end,
            source="MANUAL",
            status="PUBLISHED",
            created_by=None,  # system
        )
        self.db.add(plan)
        await self.db.flush()
        return plan

    async def create_entry(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        entry_date: date,
        shift_id: Optional[uuid.UUID] = None,
        shift_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        working_hours: Optional[float] = None,
        break_time: Optional[float] = None,
        location: Optional[str] = None,
        status: str = "Approved",
        notes: Optional[str] = None,
    ) -> ShiftPlanEntry:
        """Create a roster entry."""
        # Validate employee
        emp_stmt = select(Employee).where(
            and_(Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted == False)
        )
        emp_result = await self.db.execute(emp_stmt)
        employee = emp_result.scalars().first()
        if not employee:
            raise ValueError("Employee not found in this company.")

        # Get or create manual plan for the month
        month_start = date(entry_date.year, entry_date.month, 1)
        if entry_date.month == 12:
            month_end = date(entry_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(entry_date.year, entry_date.month + 1, 1) - timedelta(days=1)

        plan = await self._get_or_create_manual_plan(company_id, month_start, month_end)

        # Check for existing entry
        existing = await self.db.execute(
            select(ShiftPlanEntry).where(
                and_(
                    ShiftPlanEntry.plan_id == plan.id,
                    ShiftPlanEntry.employee_id == employee_id,
                    ShiftPlanEntry.shift_date == entry_date,
                )
            )
        )
        if existing.scalars().first():
            raise ValueError("Roster entry already exists for this employee on this date.")

        # Validate times
        if start_time:
            start_time = parse_time_str(start_time).strftime("%H:%M")
        if end_time:
            end_time = parse_time_str(end_time).strftime("%H:%M")

        # Determine approval status
        approval_status = EntryApprovalStatus.APPROVED
        if status == "Pending":
            approval_status = EntryApprovalStatus.PENDING
        elif status == "Rejected":
            approval_status = EntryApprovalStatus.REJECTED

        # Validate shift_type if provided
        shift_type_enum = None
        if shift_type:
            try:
                shift_type_enum = ShiftType(shift_type)
            except ValueError:
                raise ValueError(f"Invalid shift_type: {shift_type}")

        entry = ShiftPlanEntry(
            plan_id=plan.id,
            company_id=company_id,
            employee_id=employee_id,
            shift_date=entry_date,
            shift_type=shift_type_enum or ShiftType.DAY,
            shift_id=shift_id,
            start_time=parse_time_str(start_time) if start_time else None,
            end_time=parse_time_str(end_time) if end_time else None,
            approval_status=approval_status,
            notes=notes,
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def update_entry(
        self,
        entry_id: uuid.UUID,
        company_id: uuid.UUID,
        shift_id: Optional[uuid.UUID] = None,
        shift_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        working_hours: Optional[float] = None,
        break_time: Optional[float] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ShiftPlanEntry:
        """Update a roster entry."""
        stmt = select(ShiftPlanEntry).where(
            and_(ShiftPlanEntry.id == entry_id, ShiftPlanEntry.company_id == company_id)
        )
        result = await self.db.execute(stmt)
        entry = result.scalars().first()
        if not entry:
            raise ValueError("Roster entry not found.")

        if shift_id is not None:
            # Validate shift exists
            shift_stmt = select(Shift).where(
                and_(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
            )
            shift_result = await self.db.execute(shift_stmt)
            if not shift_result.scalars().first():
                raise ValueError("Shift not found.")
            entry.shift_id = shift_id

        if shift_type is not None:
            try:
                entry.shift_type = ShiftType(shift_type)
            except ValueError:
                raise ValueError(f"Invalid shift_type: {shift_type}")

        if start_time is not None:
            entry.start_time = parse_time_str(start_time)
        if end_time is not None:
            entry.end_time = parse_time_str(end_time)
        if working_hours is not None:
            # Store in notes or separate field if added
            pass
        if break_time is not None:
            pass
        if location is not None:
            pass
        if status is not None:
            if status == "Approved":
                entry.approval_status = EntryApprovalStatus.APPROVED
            elif status == "Pending":
                entry.approval_status = EntryApprovalStatus.PENDING
            elif status == "Rejected":
                entry.approval_status = EntryApprovalStatus.REJECTED
            else:
                raise ValueError("Invalid status")
        if notes is not None:
            entry.notes = notes

        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def delete_entry(self, entry_id: uuid.UUID, company_id: uuid.UUID) -> bool:
        """Delete a roster entry."""
        stmt = select(ShiftPlanEntry).where(
            and_(ShiftPlanEntry.id == entry_id, ShiftPlanEntry.company_id == company_id)
        )
        result = await self.db.execute(stmt)
        entry = result.scalars().first()
        if not entry:
            raise ValueError("Roster entry not found.")

        await self.db.delete(entry)
        await self.db.commit()
        return True

    async def list_entries(
        self,
        company_id: uuid.UUID,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        department: Optional[str] = None,
        employee_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List roster entries with derived fields."""
        # Build query joining employee for derived fields
        stmt = select(ShiftPlanEntry, Employee).join(
            Employee, ShiftPlanEntry.employee_id == Employee.id
        ).where(
            and_(ShiftPlanEntry.company_id == company_id)
        )

        if date_from:
            stmt = stmt.where(ShiftPlanEntry.shift_date >= date_from)
        if date_to:
            stmt = stmt.where(ShiftPlanEntry.shift_date <= date_to)
        if employee_id:
            stmt = stmt.where(ShiftPlanEntry.employee_id == employee_id)
        if department:
            stmt = stmt.where(Employee.department == department)

        # Only show approved entries from published plans
        stmt = stmt.join(ShiftPlanEntry.plan).where(
            ShiftPlanEntry.approval_status == EntryApprovalStatus.APPROVED,
            ShiftPlanEntry.plan.has(status="PUBLISHED"),
        )

        # Total count
        count_stmt = select(func.count(ShiftPlanEntry.id)).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginated
        stmt = stmt.order_by(ShiftPlanEntry.shift_date, Employee.first_name).offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        rows = result.all()

        items = []
        for entry, employee in rows:
            # Get manager name
            manager_name = None
            if employee.manager_id:
                mgr_stmt = select(Employee).where(Employee.id == employee.manager_id)
                mgr_result = await self.db.execute(mgr_stmt)
                mgr = mgr_result.scalars().first()
                if mgr:
                    manager_name = f"{mgr.first_name} {mgr.last_name}"

            # Determine shift name
            shift_name = entry.shift_type.value
            if entry.shift_id:
                shift_stmt = select(Shift).where(Shift.id == entry.shift_id)
                shift_result = await self.db.execute(shift_stmt)
                shift = shift_result.scalars().first()
                if shift:
                    shift_name = shift.name

            # Working hours
            wh = None
            if entry.start_time and entry.end_time:
                is_overnight = entry.end_time < entry.start_time
                if is_overnight:
                    wh = round((24 - entry.start_time.hour - entry.start_time.minute / 60) + (entry.end_time.hour + entry.end_time.minute / 60), 2)
                else:
                    wh = round((entry.end_time.hour - entry.start_time.hour) + (entry.end_time.minute - entry.start_time.minute) / 60, 2)

            items.append({
                "id": entry.id,
                "employee_id": employee.id,
                "employee_name": f"{employee.first_name} {employee.last_name}",
                "department": employee.department,
                "designation": employee.designation,
                "date": entry.shift_date,
                "shift": shift_name,
                "shift_id": entry.shift_id,
                "start_time": entry.start_time.strftime("%H:%M") if entry.start_time else None,
                "end_time": entry.end_time.strftime("%H:%M") if entry.end_time else None,
                "working_hours": wh,
                "break_time": 0.0,  # Would come from shift
                "location": None,
                "manager": manager_name,
                "status": entry.approval_status.value.title(),
            })

        return items, total


# Need to import timedelta and time
from datetime import timedelta, time