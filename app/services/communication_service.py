"""Internal Communication service layer coordinating alerts feed, news articles, and polls voting."""

from __future__ import annotations

import logging
import math
import uuid
from datetime import date, datetime, timezone

from fastapi import Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.db.database import get_db_session
from app.repositories.communication_repository import CommunicationRepository
from app.schemas.communication import (
    AnnouncementCreate,
    AnnouncementResponse,
    CompanyEventCreate,
    CompanyEventResponse,
    CompanyNewsCreate,
    CompanyNewsResponse,
    CommunicationDashboardView,
    OptionResponse,
    PollCreate,
    PollResponse,
)

logger = logging.getLogger(__name__)


class CommunicationService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: CommunicationRepository,
    ) -> None:
        self.session = session
        self.repo = repo

    # ------------------------------------------------------------------
    # Announcements Operations
    # ------------------------------------------------------------------

    async def create_announcement(self, user_id: uuid.UUID, payload: AnnouncementCreate) -> AnnouncementResponse:
        logger.info("create_announcement | title=%s", payload.title)
        try:
            ann_kwargs = payload.model_dump()
            ann_kwargs["created_by"] = user_id
            ann_kwargs["status"] = payload.status.upper()
            ann_kwargs["priority"] = payload.priority.upper()

            ann = await self.repo.create_announcement(**ann_kwargs)

            # Audit
            await self.repo.create_audit_log(
                user_id=user_id,
                action="CREATE",
                target_type="ANNOUNCEMENT",
                target_id=ann.id,
                details=f"Created announcement draft: {payload.title}",
            )

            await self.session.commit()
            full_ann = await self.repo.get_announcement_by_id(ann.id)
            return AnnouncementResponse.model_validate(full_ann)

        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_announcement: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def publish_announcement(self, user_id: uuid.UUID, ann_uuid: uuid.UUID) -> AnnouncementResponse:
        logger.info("publish_announcement | ann_id=%s", ann_uuid)
        try:
            ann = await self.repo.get_announcement_by_id(ann_uuid)
            if not ann:
                raise AppException(message="Announcement not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_announcement(ann_uuid, status="PUBLISHED", publish_date=date.today())

            await self.repo.create_audit_log(
                user_id=user_id,
                action="PUBLISH",
                target_type="ANNOUNCEMENT",
                target_id=ann_uuid,
                details="Published announcement to target feed.",
            )

            await self.session.commit()
            updated = await self.repo.get_announcement_by_id(ann_uuid)
            return AnnouncementResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("publish_announcement: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def archive_announcement(self, user_id: uuid.UUID, ann_uuid: uuid.UUID) -> AnnouncementResponse:
        try:
            ann = await self.repo.get_announcement_by_id(ann_uuid)
            if not ann:
                raise AppException(message="Announcement not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_announcement(ann_uuid, status="ARCHIVED")

            await self.repo.create_audit_log(
                user_id=user_id,
                action="ARCHIVE",
                target_type="ANNOUNCEMENT",
                target_id=ann_uuid,
                details="Archived announcement.",
            )

            await self.session.commit()
            updated = await self.repo.get_announcement_by_id(ann_uuid)
            return AnnouncementResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("archive_announcement: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_announcement(self, user_id: uuid.UUID, ann_uuid: uuid.UUID) -> AnnouncementResponse:
        try:
            ann = await self.repo.get_announcement_by_id(ann_uuid)
            if not ann:
                raise AppException(message="Announcement not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Auto read receipts trigger
            if ann.status == "PUBLISHED":
                await self.repo.mark_announcement_read(ann_uuid, user_id)
                await self.session.commit()

            return AnnouncementResponse.model_validate(ann)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_announcement: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_announcements(
        self,
        status: str | None = None,
        priority: str | None = None,
        department: str | None = None,
        branch: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> list[AnnouncementResponse]:
        try:
            offset = (page - 1) * limit
            anns = await self.repo.list_announcements(
                status=status,
                priority=priority,
                department=department,
                branch=branch,
                search=search,
                limit=limit,
                offset=offset,
            )
            return [AnnouncementResponse.model_validate(a) for a in anns]
        except SQLAlchemyError as exc:
            logger.exception("list_announcements: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_announcement(self, user_id: uuid.UUID, ann_uuid: uuid.UUID, payload: AnnouncementCreate) -> AnnouncementResponse:
        try:
            ann = await self.repo.get_announcement_by_id(ann_uuid)
            if not ann:
                raise AppException(message="Announcement not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump()
            data["status"] = payload.status.upper()
            data["priority"] = payload.priority.upper()

            await self.repo.update_announcement(ann_uuid, **data)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="UPDATE",
                target_type="ANNOUNCEMENT",
                target_id=ann_uuid,
                details=f"Updated announcement metadata: {payload.title}",
            )

            await self.session.commit()
            updated = await self.repo.get_announcement_by_id(ann_uuid)
            return AnnouncementResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_announcement: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_announcement(self, user_id: uuid.UUID, ann_uuid: uuid.UUID) -> None:
        try:
            ann = await self.repo.get_announcement_by_id(ann_uuid)
            if not ann:
                raise AppException(message="Announcement not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.soft_delete_announcement(ann_uuid)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="DELETE",
                target_type="ANNOUNCEMENT",
                target_id=ann_uuid,
                details="Soft deleted announcement.",
            )

            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_announcement: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Company News Operations
    # ------------------------------------------------------------------

    async def create_news(self, user_id: uuid.UUID, payload: CompanyNewsCreate) -> CompanyNewsResponse:
        try:
            news_kwargs = payload.model_dump()
            news_kwargs["author_id"] = user_id
            news_kwargs["status"] = payload.status.upper()

            news = await self.repo.create_news(**news_kwargs)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="CREATE",
                target_type="NEWS",
                target_id=news.id,
                details=f"Created company news headline: {payload.headline}",
            )

            await self.session.commit()
            return CompanyNewsResponse.model_validate(news)

        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_news: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_news(self, user_id: uuid.UUID, news_uuid: uuid.UUID) -> CompanyNewsResponse:
        try:
            news = await self.repo.get_news_by_id(news_uuid)
            if not news:
                raise AppException(message="Company news article not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Increment views
            if news.status == "PUBLISHED":
                await self.repo.increment_news_views(news_uuid)
                await self.session.commit()

            # Re-fetch with incremented count
            full_news = await self.repo.get_news_by_id(news_uuid)
            return CompanyNewsResponse.model_validate(full_news)

        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_news: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_news(
        self,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> list[CompanyNewsResponse]:
        try:
            offset = (page - 1) * limit
            articles = await self.repo.list_news(
                status=status,
                category=category,
                search=search,
                limit=limit,
                offset=offset,
            )
            return [CompanyNewsResponse.model_validate(a) for a in articles]
        except SQLAlchemyError as exc:
            logger.exception("list_news: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_news(self, user_id: uuid.UUID, news_uuid: uuid.UUID, payload: CompanyNewsCreate) -> CompanyNewsResponse:
        try:
            news = await self.repo.get_news_by_id(news_uuid)
            if not news:
                raise AppException(message="News article not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump()
            data["status"] = payload.status.upper()

            await self.repo.update_news(news_uuid, **data)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="UPDATE",
                target_type="NEWS",
                target_id=news_uuid,
                details=f"Updated news details: {payload.headline}",
            )

            await self.session.commit()
            updated = await self.repo.get_news_by_id(news_uuid)
            return CompanyNewsResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_news: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_news(self, user_id: uuid.UUID, news_uuid: uuid.UUID) -> None:
        try:
            news = await self.repo.get_news_by_id(news_uuid)
            if not news:
                raise AppException(message="News article not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.soft_delete_news(news_uuid)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="DELETE",
                target_type="NEWS",
                target_id=news_uuid,
                details="Soft deleted news article.",
            )

            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_news: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Company Events Operations
    # ------------------------------------------------------------------

    async def create_event(self, user_id: uuid.UUID, payload: CompanyEventCreate) -> CompanyEventResponse:
        try:
            event_kwargs = payload.model_dump()
            event_kwargs["organizer_id"] = user_id
            event_kwargs["status"] = payload.status.upper()

            event = await self.repo.create_event(**event_kwargs)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="CREATE",
                target_type="EVENT",
                target_id=event.id,
                details=f"Scheduled company event: {payload.event_title}",
            )

            await self.session.commit()
            return CompanyEventResponse.model_validate(event)

        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_events(self, status: str | None = None, event_type: str | None = None) -> list[CompanyEventResponse]:
        try:
            events = await self.repo.list_events(status=status, event_type=event_type)
            return [CompanyEventResponse.model_validate(e) for e in events]
        except SQLAlchemyError as exc:
            logger.exception("list_events: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_event(self, event_uuid: uuid.UUID) -> CompanyEventResponse:
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Company event not found.", status_code=status.HTTP_404_NOT_FOUND)
            return CompanyEventResponse.model_validate(event)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_event(self, user_id: uuid.UUID, event_uuid: uuid.UUID, payload: CompanyEventCreate) -> CompanyEventResponse:
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Event not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump()
            data["status"] = payload.status.upper()

            await self.repo.update_event(event_uuid, **data)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="UPDATE",
                target_type="EVENT",
                target_id=event_uuid,
                details=f"Updated company event fields: {payload.event_title}",
            )

            await self.session.commit()
            updated = await self.repo.get_event_by_id(event_uuid)
            return CompanyEventResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_event(self, user_id: uuid.UUID, event_uuid: uuid.UUID) -> None:
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Event not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.delete_event(event_uuid)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="DELETE",
                target_type="EVENT",
                target_id=event_uuid,
                details="Cancelled / deleted event.",
            )

            await self.session.commit()
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_event: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def register_event_participant(self, user_id: uuid.UUID, event_uuid: uuid.UUID) -> CompanyEventResponse:
        try:
            event = await self.repo.get_event_by_id(event_uuid)
            if not event:
                raise AppException(message="Event not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Limit checking
            if event.max_participants and len(event.registrations) >= event.max_participants:
                raise ConflictException(message="This event is already full. Registrations closed.")

            await self.repo.register_for_event(event_uuid, user_id)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="REGISTER",
                target_type="EVENT",
                target_id=event_uuid,
                details="Registered for company event.",
            )

            await self.session.commit()
            updated = await self.repo.get_event_by_id(event_uuid)
            return CompanyEventResponse.model_validate(updated)

        except (ConflictException, AppException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("register_event_participant: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Polls Operations
    # ------------------------------------------------------------------

    async def create_poll(self, user_id: uuid.UUID, payload: PollCreate) -> PollResponse:
        try:
            poll_kwargs = payload.model_dump(exclude={"options"})
            poll_kwargs["created_by"] = user_id
            poll_kwargs["status"] = "OPEN"

            poll = await self.repo.create_poll(**poll_kwargs)

            # Options seed
            for opt in payload.options:
                await self.repo.add_poll_option(poll.id, opt.option_text)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="CREATE",
                target_type="POLL",
                target_id=poll.id,
                details=f"Created poll question: {payload.question}",
            )

            await self.session.commit()
            full_poll = await self.repo.get_poll_by_id(poll.id)
            return PollResponse.model_validate(full_poll)

        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_poll: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_poll(self, poll_uuid: uuid.UUID) -> PollResponse:
        try:
            poll = await self.repo.get_poll_by_id(poll_uuid)
            if not poll:
                raise AppException(message="Poll not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            # Check expiry dates closing poll
            if poll.status == "OPEN" and poll.end_date < date.today():
                await self.repo.update_poll(poll_uuid, status="CLOSED")
                await self.session.commit()
                # Re-fetch
                poll = await self.repo.get_poll_by_id(poll_uuid)

            return PollResponse.model_validate(poll)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_poll: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_polls(self, status: str | None = None) -> list[PollResponse]:
        try:
            polls = await self.repo.list_polls(status)
            return [PollResponse.model_validate(p) for p in polls]
        except SQLAlchemyError as exc:
            logger.exception("list_polls: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def cast_poll_vote(self, user_id: uuid.UUID, poll_uuid: uuid.UUID, option_uuid: uuid.UUID) -> PollResponse:
        logger.info("cast_poll_vote | user=%s | poll=%s", user_id, poll_uuid)
        try:
            poll = await self.repo.get_poll_by_id(poll_uuid)
            if not poll:
                raise AppException(message="Poll not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Check open status
            if poll.status != "OPEN" or poll.end_date < date.today():
                raise AppException(message="This poll is closed.", status_code=status.HTTP_400_BAD_REQUEST)

            # Check option exists
            if not any(opt.id == option_uuid for opt in poll.options):
                raise AppException(message="Option not found in this poll.", status_code=status.HTTP_404_NOT_FOUND)

            # Vote duplicate guard
            voted = await self.repo.check_user_voted(poll_uuid, user_id)
            if voted and not poll.allow_multiple_selection:
                raise ConflictException(message="You have already voted on this poll.")

            # Cast vote
            v_user = None if poll.anonymous_voting else user_id
            await self.repo.cast_vote(poll_uuid, option_uuid, v_user)

            await self.repo.create_audit_log(
                user_id=user_id,
                action="VOTE",
                target_type="POLL",
                target_id=poll_uuid,
                details="Casted vote on option.",
            )

            await self.session.commit()
            updated = await self.repo.get_poll_by_id(poll_uuid)
            return PollResponse.model_validate(updated)

        except (ConflictException, AppException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("cast_poll_vote: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def close_poll(self, user_id: uuid.UUID, poll_uuid: uuid.UUID) -> PollResponse:
        try:
            poll = await self.repo.get_poll_by_id(poll_uuid)
            if not poll:
                raise AppException(message="Poll not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_poll(poll_uuid, status="CLOSED")

            await self.repo.create_audit_log(
                user_id=user_id,
                action="UPDATE",
                target_type="POLL",
                target_id=poll_uuid,
                details="Closed poll manually.",
            )

            await self.session.commit()
            updated = await self.repo.get_poll_by_id(poll_uuid)
            return PollResponse.model_validate(updated)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("close_poll: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Communication Dashboard Aggregation
    # ------------------------------------------------------------------

    async def get_dashboard(self) -> CommunicationDashboardView:
        try:
            today = date.today()

            # Pinned announcements
            pinned = await self.repo.list_announcements(status="PUBLISHED", is_pinned=True, limit=5)
            
            # Recent announcements
            recent = await self.repo.list_announcements(status="PUBLISHED", is_pinned=False, limit=10)

            # News articles
            news = await self.repo.list_news(status="PUBLISHED", limit=10)

            # Upcoming events (next 30 days)
            events = await self.repo.list_events(status="SCHEDULED", start_date=today, limit=10)

            # Active polls
            all_polls = await self.repo.list_polls(status="OPEN")
            active_polls = [p for p in all_polls if p.end_date >= today]

            return CommunicationDashboardView(
                pinned_announcements=[AnnouncementResponse.model_validate(p) for p in pinned],
                recent_announcements=[AnnouncementResponse.model_validate(r) for r in recent],
                company_news=[CompanyNewsResponse.model_validate(n) for n in news],
                upcoming_events=[CompanyEventResponse.model_validate(e) for e in events],
                active_polls=[PollResponse.model_validate(p) for p in active_polls],
            )

        except SQLAlchemyError as exc:
            logger.exception("get_dashboard: db error", exc_info=exc)
            raise DatabaseException() from exc


async def get_communication_service(
    session: AsyncSession = Depends(get_db_session),
) -> CommunicationService:
    return CommunicationService(
        session=session,
        repo=CommunicationRepository(session),
    )
