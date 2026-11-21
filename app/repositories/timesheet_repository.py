"""Timesheet Repository: async database operations for timesheets."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.timesheet import Timesheet, TimesheetEntry
from app.models.employee import Employee

logger = logging.getLogger(__name__)


class TimesheetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_timesheet_by_id(self, timesheet_id: uuid.UUID, company_id: uuid.UUID | None = None) -> Timesheet | None:
        stmt = (
            select(Timesheet)
            .join(Employee, Timesheet.employee_id == Employee.id)
            .where(Timesheet.id == timesheet_id)
            .options(selectinload(Timesheet.entries))
        )
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_timesheet_by_week(self, employee_id: uuid.UUID, week_start_date: date, company_id: uuid.UUID | None = None) -> Timesheet | None:
        stmt = (
            select(Timesheet)
            .join(Employee, Timesheet.employee_id == Employee.id)
            .where(
                and_(
                    Timesheet.employee_id == employee_id,
                    Timesheet.week_start_date == week_start_date
                )
            )
            .options(selectinload(Timesheet.entries))
        )
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_timesheets_for_employee(self, employee_id: uuid.UUID, company_id: uuid.UUID | None = None) -> list[Timesheet]:
        stmt = (
            select(Timesheet)
            .join(Employee, Timesheet.employee_id == Employee.id)
            .where(Timesheet.employee_id == employee_id)
            .order_by(Timesheet.week_start_date.desc())
            .options(selectinload(Timesheet.entries))
        )
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_pending_timesheets(self, company_id: uuid.UUID, manager_employee_id: uuid.UUID | None = None, role: str | None = None) -> list[Timesheet]:
        """Get pending timesheets with tenant isolation and role-based filtering.
        
        Args:
            company_id: Company UUID for tenant isolation
            manager_employee_id: Employee ID of the manager (for manager role filtering)
            role: User role (hr_admin, manager, super_admin, etc.)
        """
        stmt = (
            select(Timesheet)
            .join(Employee, Timesheet.employee_id == Employee.id)
            .where(
                and_(
                    Timesheet.status == "PENDING",
                    Employee.company_id == company_id
                )
            )
            .order_by(Timesheet.week_start_date.desc())
            .options(
                selectinload(Timesheet.entries),
                selectinload(Timesheet.employee)
            )
        )

        # Role-based filtering
        if role and role.lower() == "manager" and manager_employee_id:
            # Manager can only see their direct/indirect reports
            # Get all employees in manager's reporting chain
            from sqlalchemy import or_
            # For simplicity, we'll filter by manager_id and reporting_manager_id
            # A more complete solution would traverse the hierarchy
            stmt = stmt.where(
                or_(
                    Employee.manager_id == manager_employee_id,
                    Employee.reporting_manager_id == manager_employee_id
                )
            )
        # HR Admin and Super Admin see all in company (no additional filter needed)

        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_timesheet(self, **kwargs) -> Timesheet:
        timesheet = Timesheet(**kwargs)
        self.session.add(timesheet)
        return timesheet

    async def create_timesheet_entry(self, **kwargs) -> TimesheetEntry:
        entry = TimesheetEntry(**kwargs)
        self.session.add(entry)
        return entry

    async def delete_timesheet_entries(self, timesheet_id: uuid.UUID) -> None:
        from sqlalchemy import delete
        await self.session.execute(
            delete(TimesheetEntry).where(TimesheetEntry.timesheet_id == timesheet_id)
        )

    async def get_timesheets_for_review(
        self,
        company_id: uuid.UUID,
        reviewer_employee_id: uuid.UUID,
        reviewer_role: str
    ) -> list[Timesheet]:
        """Get timesheets that the reviewer is authorized to review."""
        if reviewer_role.lower() in ("hr_admin", "super_admin", "executive"):
            # HR Admin and Super Admin can review all in company
            return await self.get_pending_timesheets(company_id=company_id, role=reviewer_role)
        elif reviewer_role.lower() == "manager":
            # Manager can only review their team's timesheets
            return await self.get_pending_timesheets(
                company_id=company_id,
                manager_employee_id=reviewer_employee_id,
                role="manager"
            )
        return []