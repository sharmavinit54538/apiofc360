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

    async def get_timesheet_by_id(self, timesheet_id: uuid.UUID) -> Timesheet | None:
        stmt = (
            select(Timesheet)
            .where(Timesheet.id == timesheet_id)
            .options(selectinload(Timesheet.entries))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_timesheet_by_week(self, employee_id: uuid.UUID, week_start_date: date) -> Timesheet | None:
        stmt = (
            select(Timesheet)
            .where(
                and_(
                    Timesheet.employee_id == employee_id,
                    Timesheet.week_start_date == week_start_date
                )
            )
            .options(selectinload(Timesheet.entries))
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_timesheets_for_employee(self, employee_id: uuid.UUID) -> list[Timesheet]:
        stmt = (
            select(Timesheet)
            .where(Timesheet.employee_id == employee_id)
            .order_by(Timesheet.week_start_date.desc())
            .options(selectinload(Timesheet.entries))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_pending_timesheets(self) -> list[Timesheet]:
        stmt = (
            select(Timesheet)
            .where(Timesheet.status == "PENDING")
            .order_by(Timesheet.week_start_date.desc())
            .options(
                selectinload(Timesheet.entries),
                selectinload(Timesheet.employee)
            )
        )
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
