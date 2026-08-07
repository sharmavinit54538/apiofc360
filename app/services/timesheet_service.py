"""Timesheet management business logic layer."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, BadRequestException
from app.models.timesheet import Timesheet
from app.repositories.timesheet_repository import TimesheetRepository
from app.schemas.timesheet import TimesheetCreate, TimesheetEntryCreate

logger = logging.getLogger(__name__)


class TimesheetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TimesheetRepository(session)

    async def get_or_create_weekly_timesheet(self, employee_id: uuid.UUID, week_start_date: date) -> Timesheet:
        timesheet = await self.repo.get_timesheet_by_week(employee_id, week_start_date)
        if not timesheet:
            timesheet = await self.repo.create_timesheet(
                employee_id=employee_id,
                week_start_date=week_start_date,
                status="DRAFT"
            )
            await self.session.commit()
            await self.session.refresh(timesheet)
        return timesheet

    async def save_timesheet_entries(
        self, employee_id: uuid.UUID, week_start_date: date, entries_data: list[TimesheetEntryCreate]
    ) -> Timesheet:
        timesheet = await self.repo.get_timesheet_by_week(employee_id, week_start_date)
        if not timesheet:
            timesheet = await self.repo.create_timesheet(
                employee_id=employee_id,
                week_start_date=week_start_date,
                status="DRAFT"
            )
            # Fetch back or flush to ensure timesheet.id is generated
            await self.session.flush()
        else:
            if timesheet.status in ("PENDING", "APPROVED"):
                raise BadRequestException(message="Cannot edit timesheet after submission.")

            # Delete old entries
            await self.repo.delete_timesheet_entries(timesheet.id)

        # Create new entries
        for entry in entries_data:
            await self.repo.create_timesheet_entry(
                timesheet_id=timesheet.id,
                project_id=entry.project_id,
                monday_hours=entry.monday_hours,
                tuesday_hours=entry.tuesday_hours,
                wednesday_hours=entry.wednesday_hours,
                thursday_hours=entry.thursday_hours,
                friday_hours=entry.friday_hours,
                saturday_hours=entry.saturday_hours,
                sunday_hours=entry.sunday_hours,
                description=entry.description
            )
        
        timesheet.status = "DRAFT"
        await self.session.commit()
        await self.session.refresh(timesheet)
        return timesheet

    async def submit_timesheet(self, employee_id: uuid.UUID, week_start_date: date) -> Timesheet:
        timesheet = await self.repo.get_timesheet_by_week(employee_id, week_start_date)
        if not timesheet:
            raise NotFoundException(message="Timesheet not found.")
        
        if timesheet.status in ("PENDING", "APPROVED"):
            raise BadRequestException(message="Timesheet is already submitted or approved.")

        # Validate total hours > 0
        total_hours = 0
        for entry in timesheet.entries:
            total_hours += (
                entry.monday_hours + entry.tuesday_hours + entry.wednesday_hours +
                entry.thursday_hours + entry.friday_hours + entry.saturday_hours +
                entry.sunday_hours
            )
        
        if total_hours == 0:
            raise BadRequestException(message="Cannot submit an empty timesheet.")

        timesheet.status = "PENDING"
        timesheet.submitted_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(timesheet)
        return timesheet

    async def get_employee_timesheet_history(self, employee_id: uuid.UUID) -> list[Timesheet]:
        return await self.repo.get_timesheets_for_employee(employee_id)

    async def get_all_pending_timesheets(self) -> list[Timesheet]:
        return await self.repo.get_pending_timesheets()

    async def review_timesheet(
        self, timesheet_id: uuid.UUID, status: str, approved_by_id: uuid.UUID, rejection_reason: str | None = None
    ) -> Timesheet:
        timesheet = await self.repo.get_timesheet_by_id(timesheet_id)
        if not timesheet:
            raise NotFoundException(message="Timesheet not found.")

        if timesheet.status != "PENDING":
            raise BadRequestException(message="Timesheet is not in PENDING state.")

        timesheet.status = status
        if status == "APPROVED":
            timesheet.approved_by_id = approved_by_id
            timesheet.rejection_reason = None
        elif status == "REJECTED":
            if not rejection_reason:
                raise BadRequestException(message="Rejection reason is required.")
            timesheet.rejection_reason = rejection_reason
            timesheet.approved_by_id = None
        
        await self.session.commit()
        await self.session.refresh(timesheet)
        return timesheet
