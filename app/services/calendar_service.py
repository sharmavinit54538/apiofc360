"""Calendar Management service layer coordinating events scheduling, birthdays, and double-booking controls."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta

from fastapi import Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.db.database import get_db_session
from app.repositories.calendar_repository import CalendarRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.calendar import (
    AnniversaryListItem,
    BirthdayListItem,
    CalendarDashboardView,
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
    HolidayCreate,
    HolidayResponse,
    MeetingCreate,
    MeetingResponse,
)

logger = logging.getLogger(__name__)


class CalendarService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: CalendarRepository,
        employee_repo: EmployeeRepository,
    ) -> None:
        self.session = session
        self.repo = repo
        self.employee_repo = employee_repo

    # ------------------------------------------------------------------
    # CalendarEvent Operations
    # ------------------------------------------------------------------

    async def create_event(self, user_id: uuid.UUID, payload: CalendarEventCreate) -> CalendarEventResponse:
        logger.info("create_event | title=%s | type=%s", payload.title, payload.event_type)
        try:
            event_kwargs = payload.model_dump(exclude={"reminder_minutes"})
            event_kwargs["created_by"] = user_id
            event_kwargs["status"] = payload.status.upper()
            event_kwargs["visibility"] = payload.visibility.upper()

            event = await self.repo.create_event(**event_kwargs)

            # Seed reminders
            for mins in payload.reminder_minutes:
                await self.repo.add_reminder(event_id=event.id, reminder_minutes_before=mins)

            await self.session.commit()
            full_event = await self.repo.get_event_by_id(event.id)
            return CalendarEventResponse.model_validate(full_event)

        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_event: db error", exc_info=exc)
            raise DatabaseException() from exc

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
    ) -> list[CalendarEventResponse]:
        try:
            events = await self.repo.list_events(
                event_type=event_type,
                department=department,
                branch=branch,
                status=status,
                visibility=visibility,
                start_date=start_date,
                end_date=end_date,
                search=search,
                limit=limit,
                offset=offset,
            )
            return [CalendarEventResponse.model_validate(e) for e in events]
        except SQLAlchemyError as exc:
            logger.exception("list_events: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_event(self, event_uuid: uuid.UUID) -> CalendarEventResponse:
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Calendar event not found.", status_code=status.HTTP_404_NOT_FOUND)
            return CalendarEventResponse.model_validate(event)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_event(self, event_uuid: uuid.UUID, payload: CalendarEventUpdate) -> CalendarEventResponse:
        logger.info("update_event | event_id=%s", event_uuid)
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Calendar event not found.", status_code=status.HTTP_404_NOT_FOUND)

            update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
            if "status" in update_data:
                update_data["status"] = update_data["status"].upper()
            if "visibility" in update_data:
                update_data["visibility"] = update_data["visibility"].upper()

            await self.repo.update_event(event_uuid, **update_data)
            await self.session.commit()
            
            full_event = await self.repo.get_event_by_id(event_uuid)
            return CalendarEventResponse.model_validate(full_event)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_event(self, event_uuid: uuid.UUID) -> None:
        logger.info("delete_event | event_id=%s", event_uuid)
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Calendar event not found.", status_code=status.HTTP_404_NOT_FOUND)
            await self.repo.soft_delete_event(event_uuid)
            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Holiday Calendar Operations
    # ------------------------------------------------------------------

    async def create_holiday(self, payload: HolidayCreate) -> HolidayResponse:
        logger.info("create_holiday | name=%s | date=%s", payload.holiday_name, payload.holiday_date)
        try:
            holiday_kwargs = payload.model_dump()
            holiday_kwargs["holiday_type"] = payload.holiday_type.upper()
            
            holiday = await self.repo.create_holiday(**holiday_kwargs)
            await self.session.commit()
            return HolidayResponse.model_validate(holiday)
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_holiday: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_holidays(self, branch: str | None = None, year: int | None = None) -> list[HolidayResponse]:
        try:
            holidays = await self.repo.list_holidays(branch=branch, year=year)
            
            # Rule: If recurring is enabled, copy/project holidays to current year if requested year differs
            # For simplicity, returning stored holidays. Recurring handles projection in frontend calendar grids.
            return [HolidayResponse.model_validate(h) for h in holidays]
        except SQLAlchemyError as exc:
            logger.exception("list_holidays: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_holiday(self, holiday_uuid: uuid.UUID, payload: HolidayCreate) -> HolidayResponse:
        try:
            holiday = await self.repo.get_holiday_by_id(holiday_uuid)
            if not holiday:
                raise AppException(message="Holiday not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump()
            data["holiday_type"] = payload.holiday_type.upper()

            await self.repo.update_holiday(holiday_uuid, **data)
            await self.session.commit()
            
            updated = await self.repo.get_holiday_by_id(holiday_uuid)
            return HolidayResponse.model_validate(updated)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_holiday: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_holiday(self, holiday_uuid: uuid.UUID) -> None:
        try:
            holiday = await self.repo.get_holiday_by_id(holiday_uuid)
            if not holiday:
                raise AppException(message="Holiday not found.", status_code=status.HTTP_404_NOT_FOUND)
            await self.repo.delete_holiday(holiday_uuid)
            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_holiday: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Meetings Operations
    # ------------------------------------------------------------------

    async def create_meeting(self, user_id: uuid.UUID, payload: MeetingCreate) -> MeetingResponse:
        logger.info("create_meeting | title=%s | date=%s", payload.meeting_title, payload.meeting_date)
        try:
            # Overlap checking
            overlapping = await self.repo.check_organizer_overlap(
                organizer_id=user_id,
                meeting_date=payload.meeting_date,
                start_time=payload.start_time,
                end_time=payload.end_time,
            )
            if overlapping:
                raise ConflictException(message="You have an overlapping meeting scheduled at this time.")

            meet_kwargs = payload.model_dump(exclude={"participant_employee_ids"})
            meet_kwargs["organizer_id"] = user_id
            meet_kwargs["meeting_mode"] = payload.meeting_mode.upper()
            meet_kwargs["status"] = "SCHEDULED"

            meeting = await self.repo.create_meeting(**meet_kwargs)

            # Invite participants
            for emp_uuid in payload.participant_employee_ids:
                await self.repo.add_meeting_participant(meeting.id, emp_uuid)

            await self.session.commit()
            full_meeting = await self.repo.get_meeting_by_id(meeting.id)
            return MeetingResponse.model_validate(full_meeting)

        except (ConflictException, AppException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_meeting: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_meeting(self, meeting_uuid: uuid.UUID) -> MeetingResponse:
        try:
            meeting = await self.repo.get_meeting_by_id(meeting_uuid)
            if not meeting:
                raise AppException(message="Meeting not found.", status_code=status.HTTP_404_NOT_FOUND)
            return MeetingResponse.model_validate(meeting)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_meeting: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_meeting(self, meeting_uuid: uuid.UUID, payload: MeetingCreate) -> MeetingResponse:
        try:
            meeting = await self.repo.get_meeting_by_id(meeting_uuid)
            if not meeting:
                raise AppException(message="Meeting not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Overlap checking excluding this meeting
            overlapping = await self.repo.check_organizer_overlap(
                organizer_id=meeting.organizer_id,
                meeting_date=payload.meeting_date,
                start_time=payload.start_time,
                end_time=payload.end_time,
                exclude_meeting_id=meeting_uuid,
            )
            if overlapping:
                raise ConflictException(message="You have an overlapping meeting scheduled at this time.")

            meet_data = payload.model_dump(exclude={"participant_employee_ids"})
            meet_data["meeting_mode"] = payload.meeting_mode.upper()

            await self.repo.update_meeting(meeting_uuid, **meet_data)

            # Refresh participants list
            await self.repo.clear_meeting_participants(meeting_uuid)
            for emp_uuid in payload.participant_employee_ids:
                await self.repo.add_meeting_participant(meeting_uuid, emp_uuid)

            await self.session.commit()
            updated = await self.repo.get_meeting_by_id(meeting_uuid)
            return MeetingResponse.model_validate(updated)

        except (ConflictException, AppException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_meeting: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_meeting(self, meeting_uuid: uuid.UUID) -> None:
        try:
            meeting = await self.repo.get_meeting_by_id(meeting_uuid)
            if not meeting:
                raise AppException(message="Meeting not found.", status_code=status.HTTP_404_NOT_FOUND)
            await self.repo.delete_meeting(meeting_uuid)
            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_meeting: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_meetings(
        self,
        organizer_id: uuid.UUID | None = None,
        meeting_date: date | None = None,
        status: str | None = None,
    ) -> list[MeetingResponse]:
        try:
            meetings = await self.repo.list_meetings(organizer_id, meeting_date, status)
            return [MeetingResponse.model_validate(m) for m in meetings]
        except SQLAlchemyError as exc:
            logger.exception("list_meetings: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Birthdays & Anniversaries Calculators
    # ------------------------------------------------------------------

    async def get_birthdays(self, target_date: date) -> list[BirthdayListItem]:
        try:
            employees = await self.repo.get_birthdays_by_date(target_date)
            results = []
            for emp in employees:
                age = target_date.year - emp.date_of_birth.year if emp.date_of_birth else 0
                results.append(
                    BirthdayListItem(
                        employee_name=f"{emp.first_name} {emp.last_name}",
                        department=emp.department or "General",
                        designation=emp.designation or "Employee",
                        age=age,
                    )
                )
            return results
        except SQLAlchemyError as exc:
            logger.exception("get_birthdays: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_anniversaries(self, target_date: date) -> list[AnniversaryListItem]:
        try:
            employees = await self.repo.get_anniversaries_by_date(target_date)
            results = []
            for emp in employees:
                years = target_date.year - emp.joining_date.year if emp.joining_date else 0
                results.append(
                    AnniversaryListItem(
                        employee_name=f"{emp.first_name} {emp.last_name}",
                        department=emp.department or "General",
                        years_completed=max(0, years),
                    )
                )
            return results
        except SQLAlchemyError as exc:
            logger.exception("get_anniversaries: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Dashboard Aggregation
    # ------------------------------------------------------------------

    async def get_dashboard(self, user_id: uuid.UUID) -> CalendarDashboardView:
        try:
            today = date.today()
            upcoming_limit = today + timedelta(days=30)

            # Get user's employee details for department filtering
            employee = await self.employee_repo.get_by_user_id(user_id)
            dept = employee.department if employee else None

            # 1. Today's Events
            today_events = await self.repo.list_events(start_date=today, end_date=today, status="PUBLISHED")
            
            # 2. Upcoming Holidays (Next 30 days)
            all_holidays = await self.repo.list_holidays()
            upcoming_holidays = [
                h for h in all_holidays 
                if today <= h.holiday_date <= upcoming_limit
            ]

            # 3. Birthdays Today
            birthdays = await self.get_birthdays(today)

            # 4. Anniversaries Today
            anniversaries = await self.get_anniversaries(today)

            # 5. Today's Meetings
            today_meetings = await self.repo.list_meetings(meeting_date=today, status="SCHEDULED")

            # 6. Upcoming Company Events (Next 30 days)
            all_events = await self.repo.list_events(event_type="Company Event", start_date=today, end_date=upcoming_limit, status="PUBLISHED")
            upcoming_company_events = [e for e in all_events if e.visibility == "PUBLIC"]

            # 7. Department Events
            department_events = []
            if dept:
                department_events = await self.repo.list_events(department=dept, status="PUBLISHED")

            return CalendarDashboardView(
                today_events=[CalendarEventResponse.model_validate(e) for e in today_events],
                upcoming_holidays=[HolidayResponse.model_validate(h) for h in upcoming_holidays],
                upcoming_birthdays=birthdays,
                upcoming_anniversaries=anniversaries,
                today_meetings=[MeetingResponse.model_validate(m) for m in today_meetings],
                upcoming_company_events=[CalendarEventResponse.model_validate(e) for e in upcoming_company_events],
                department_events=[CalendarEventResponse.model_validate(e) for e in department_events],
            )

        except SQLAlchemyError as exc:
            logger.exception("get_dashboard: db error", exc_info=exc)
            raise DatabaseException() from exc


async def get_calendar_service(
    session: AsyncSession = Depends(get_db_session),
) -> CalendarService:
    return CalendarService(
        session=session,
        repo=CalendarRepository(session),
        employee_repo=EmployeeRepository(session),
    )
