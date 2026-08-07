"""Calendar Management repository layer: direct database operations."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import and_, func, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.calendar import (
    CalendarEvent,
    HolidayCalendar,
    Meeting,
    MeetingParticipant,
    CalendarNotification,
    EventReminder,
)
from app.models.employee import Employee
from app.models.user import User

logger = logging.getLogger(__name__)


class CalendarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _event_active_filter(self):
        return CalendarEvent.is_deleted == False  # noqa: E712

    # ------------------------------------------------------------------
    # CalendarEvent CRUD
    # ------------------------------------------------------------------

    async def create_event(self, **kwargs: Any) -> CalendarEvent:
        obj = CalendarEvent(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_event_by_id(self, event_uuid: uuid.UUID) -> CalendarEvent | None:
        result = await self.session.execute(
            select(CalendarEvent)
            .where(and_(CalendarEvent.id == event_uuid, self._event_active_filter()))
            .options(selectinload(CalendarEvent.reminders))
        )
        return result.scalar_one_or_none()

    async def list_events(
        self,
        event_type: str | None = None,
        department: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        visibility: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CalendarEvent]:
        stmt = select(CalendarEvent).where(self._event_active_filter())

        if event_type:
            stmt = stmt.where(CalendarEvent.event_type == event_type)
        if department:
            stmt = stmt.where(CalendarEvent.department == department)
        if branch:
            stmt = stmt.where(CalendarEvent.branch == branch)
        if status:
            stmt = stmt.where(CalendarEvent.status == status.upper())
        if visibility:
            stmt = stmt.where(CalendarEvent.visibility == visibility.upper())
        if start_date:
            stmt = stmt.where(CalendarEvent.start_date >= start_date)
        if end_date:
            stmt = stmt.where(CalendarEvent.end_date <= end_date)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    CalendarEvent.title.ilike(pattern),
                    CalendarEvent.description.ilike(pattern),
                )
            )

        stmt = stmt.order_by(CalendarEvent.start_date.asc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_event(self, event_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(CalendarEvent).where(CalendarEvent.id == event_uuid).values(**kwargs)
        )

    async def soft_delete_event(self, event_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(CalendarEvent)
            .where(CalendarEvent.id == event_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    # ------------------------------------------------------------------
    # HolidayCalendar CRUD
    # ------------------------------------------------------------------

    async def create_holiday(self, **kwargs: Any) -> HolidayCalendar:
        obj = HolidayCalendar(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_holiday_by_id(self, holiday_uuid: uuid.UUID) -> HolidayCalendar | None:
        result = await self.session.execute(
            select(HolidayCalendar).where(HolidayCalendar.id == holiday_uuid)
        )
        return result.scalar_one_or_none()

    async def list_holidays(self, branch: str | None = None, year: int | None = None) -> list[HolidayCalendar]:
        stmt = select(HolidayCalendar)
        if branch:
            stmt = stmt.where(HolidayCalendar.branch == branch)
        if year:
            stmt = stmt.where(func.extract("year", HolidayCalendar.holiday_date) == year)
        stmt = stmt.order_by(HolidayCalendar.holiday_date.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_holiday(self, holiday_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(HolidayCalendar).where(HolidayCalendar.id == holiday_uuid).values(**kwargs)
        )

    async def delete_holiday(self, holiday_uuid: uuid.UUID) -> None:
        await self.session.execute(
            delete(HolidayCalendar).where(HolidayCalendar.id == holiday_uuid)
        )

    # ------------------------------------------------------------------
    # Meeting & Participant CRUD
    # ------------------------------------------------------------------

    async def create_meeting(self, **kwargs: Any) -> Meeting:
        obj = Meeting(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_meeting_by_id(self, meeting_uuid: uuid.UUID) -> Meeting | None:
        result = await self.session.execute(
            select(Meeting)
            .where(Meeting.id == meeting_uuid)
            .options(
                selectinload(Meeting.organizer),
                selectinload(Meeting.participants).selectinload(MeetingParticipant.employee),
                selectinload(Meeting.reminders),
            )
        )
        return result.scalar_one_or_none()

    async def list_meetings(
        self,
        organizer_id: uuid.UUID | None = None,
        meeting_date: date | None = None,
        status: str | None = None,
    ) -> list[Meeting]:
        stmt = select(Meeting).options(
            selectinload(Meeting.organizer),
            selectinload(Meeting.participants).selectinload(MeetingParticipant.employee),
        )
        if organizer_id:
            stmt = stmt.where(Meeting.organizer_id == organizer_id)
        if meeting_date:
            stmt = stmt.where(Meeting.meeting_date == meeting_date)
        if status:
            stmt = stmt.where(Meeting.status == status.upper())

        stmt = stmt.order_by(Meeting.meeting_date.asc(), Meeting.start_time.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_meeting(self, meeting_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Meeting).where(Meeting.id == meeting_uuid).values(**kwargs)
        )

    async def delete_meeting(self, meeting_uuid: uuid.UUID) -> None:
        await self.session.execute(
            delete(Meeting).where(Meeting.id == meeting_uuid)
        )

    async def add_meeting_participant(self, meeting_uuid: uuid.UUID, employee_uuid: uuid.UUID) -> MeetingParticipant:
        obj = MeetingParticipant(meeting_id=meeting_uuid, employee_id=employee_uuid)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def clear_meeting_participants(self, meeting_uuid: uuid.UUID) -> None:
        await self.session.execute(
            delete(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_uuid)
        )

    async def check_organizer_overlap(
        self,
        organizer_id: uuid.UUID,
        meeting_date: date,
        start_time: time,
        end_time: time,
        exclude_meeting_id: uuid.UUID | None = None,
    ) -> bool:
        """Check if organizer has an overlapping meeting scheduled on the same date."""
        stmt = select(Meeting).where(
            and_(
                Meeting.organizer_id == organizer_id,
                Meeting.meeting_date == meeting_date,
                Meeting.status == "SCHEDULED",
                or_(
                    and_(Meeting.start_time <= start_time, Meeting.end_time > start_time),
                    and_(Meeting.start_time < end_time, Meeting.end_time >= end_time),
                    and_(Meeting.start_time >= start_time, Meeting.end_time <= end_time),
                ),
            )
        )
        if exclude_meeting_id:
            stmt = stmt.where(Meeting.id != exclude_meeting_id)

        result = await self.session.execute(stmt)
        overlapping = result.scalars().first()
        return overlapping is not None

    # ------------------------------------------------------------------
    # Automated Birthday & Anniversary Query methods
    # ------------------------------------------------------------------

    async def get_birthdays_by_date(self, target_date: date) -> list[Employee]:
        """Fetch active employees whose birthday matches target_date month and day."""
        stmt = select(Employee).where(
            and_(
                Employee.status == "ACTIVE",
                func.extract("month", Employee.date_of_birth) == target_date.month,
                func.extract("day", Employee.date_of_birth) == target_date.day,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_anniversaries_by_date(self, target_date: date) -> list[Employee]:
        """Fetch active employees whose joining anniversary matches target_date month and day."""
        stmt = select(Employee).where(
            and_(
                Employee.status == "ACTIVE",
                func.extract("month", Employee.joining_date) == target_date.month,
                func.extract("day", Employee.joining_date) == target_date.day,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Reminders & Notifications
    # ------------------------------------------------------------------

    async def add_reminder(self, **kwargs: Any) -> EventReminder:
        obj = EventReminder(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def clear_reminders(self, event_id: uuid.UUID | None = None, meeting_id: uuid.UUID | None = None) -> None:
        if event_id:
            await self.session.execute(delete(EventReminder).where(EventReminder.event_id == event_id))
        if meeting_id:
            await self.session.execute(delete(EventReminder).where(EventReminder.meeting_id == meeting_id))

    async def create_notification(self, **kwargs: Any) -> CalendarNotification:
        obj = CalendarNotification(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj
