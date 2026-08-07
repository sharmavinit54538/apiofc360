"""Internal Communication repository layer: direct database operations."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.communication import (
    Announcement,
    AnnouncementRead,
    CompanyNews,
    CompanyEvent,
    EventRegistration,
    Poll,
    PollOption,
    PollVote,
    NotificationCenter,
    CommunicationAuditLog,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class CommunicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _announcement_active_filter(self):
        return Announcement.is_deleted == False  # noqa: E712

    def _news_active_filter(self):
        return CompanyNews.is_deleted == False  # noqa: E712

    # ------------------------------------------------------------------
    # Announcement CRUD
    # ------------------------------------------------------------------

    async def create_announcement(self, **kwargs: Any) -> Announcement:
        obj = Announcement(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_announcement_by_id(self, ann_uuid: uuid.UUID) -> Announcement | None:
        result = await self.session.execute(
            select(Announcement)
            .where(and_(Announcement.id == ann_uuid, self._announcement_active_filter()))
            .options(selectinload(Announcement.reads))
        )
        return result.scalar_one_or_none()

    async def list_announcements(
        self,
        status: str | None = None,
        priority: str | None = None,
        department: str | None = None,
        branch: str | None = None,
        search: str | None = None,
        is_pinned: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Announcement]:
        stmt = select(Announcement).where(self._announcement_active_filter())

        if status:
            stmt = stmt.where(Announcement.status == status.upper())
        if priority:
            stmt = stmt.where(Announcement.priority == priority.upper())
        if department:
            stmt = stmt.where(Announcement.department == department)
        if branch:
            stmt = stmt.where(Announcement.branch == branch)
        if is_pinned is not None:
            stmt = stmt.where(Announcement.is_pinned == is_pinned)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Announcement.title.ilike(pattern),
                    Announcement.description.ilike(pattern),
                )
            )

        # Order by Pinned first, then publish date
        stmt = stmt.order_by(Announcement.is_pinned.desc(), Announcement.publish_date.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_announcements(
        self,
        status: str | None = None,
        priority: str | None = None,
        department: str | None = None,
        branch: str | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Announcement).where(self._announcement_active_filter())

        if status:
            stmt = stmt.where(Announcement.status == status.upper())
        if priority:
            stmt = stmt.where(Announcement.priority == priority.upper())
        if department:
            stmt = stmt.where(Announcement.department == department)
        if branch:
            stmt = stmt.where(Announcement.branch == branch)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Announcement.title.ilike(pattern),
                    Announcement.description.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_announcement(self, ann_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Announcement).where(Announcement.id == ann_uuid).values(**kwargs)
        )

    async def soft_delete_announcement(self, ann_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(Announcement)
            .where(Announcement.id == ann_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    async def mark_announcement_read(self, ann_uuid: uuid.UUID, user_uuid: uuid.UUID) -> AnnouncementRead:
        result = await self.session.execute(
            select(AnnouncementRead).where(
                and_(
                    AnnouncementRead.announcement_id == ann_uuid,
                    AnnouncementRead.user_id == user_uuid,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        obj = AnnouncementRead(announcement_id=ann_uuid, user_id=user_uuid)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # CompanyNews CRUD
    # ------------------------------------------------------------------

    async def create_news(self, **kwargs: Any) -> CompanyNews:
        obj = CompanyNews(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_news_by_id(self, news_uuid: uuid.UUID) -> CompanyNews | None:
        result = await self.session.execute(
            select(CompanyNews).where(and_(CompanyNews.id == news_uuid, self._news_active_filter()))
        )
        return result.scalar_one_or_none()

    async def list_news(
        self,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[CompanyNews]:
        stmt = select(CompanyNews).where(self._news_active_filter())

        if status:
            stmt = stmt.where(CompanyNews.status == status.upper())
        if category:
            stmt = stmt.where(CompanyNews.category == category)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    CompanyNews.headline.ilike(pattern),
                    CompanyNews.summary.ilike(pattern),
                )
            )

        stmt = stmt.order_by(CompanyNews.publish_date.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_news(
        self,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(CompanyNews).where(self._news_active_filter())

        if status:
            stmt = stmt.where(CompanyNews.status == status.upper())
        if category:
            stmt = stmt.where(CompanyNews.category == category)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    CompanyNews.headline.ilike(pattern),
                    CompanyNews.summary.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def increment_news_views(self, news_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(CompanyNews)
            .where(CompanyNews.id == news_uuid)
            .values(views_count=CompanyNews.views_count + 1)
        )

    async def update_news(self, news_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(CompanyNews).where(CompanyNews.id == news_uuid).values(**kwargs)
        )

    async def soft_delete_news(self, news_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(CompanyNews)
            .where(CompanyNews.id == news_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    # ------------------------------------------------------------------
    # CompanyEvent CRUD
    # ------------------------------------------------------------------

    async def create_event(self, **kwargs: Any) -> CompanyEvent:
        obj = CompanyEvent(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_event_by_id(self, event_uuid: uuid.UUID) -> CompanyEvent | None:
        result = await self.session.execute(
            select(CompanyEvent)
            .where(CompanyEvent.id == event_uuid)
            .options(selectinload(CompanyEvent.registrations))
        )
        return result.scalar_one_or_none()

    async def list_events(
        self,
        status: str | None = None,
        event_type: str | None = None,
        start_date: date | None = None,
        limit: int = 50,
    ) -> list[CompanyEvent]:
        stmt = select(CompanyEvent)
        if status:
            stmt = stmt.where(CompanyEvent.status == status.upper())
        if event_type:
            stmt = stmt.where(CompanyEvent.event_type == event_type)
        if start_date:
            stmt = stmt.where(CompanyEvent.start_date >= start_date)

        stmt = stmt.order_by(CompanyEvent.start_date.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_event(self, event_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(CompanyEvent).where(CompanyEvent.id == event_uuid).values(**kwargs)
        )

    async def delete_event(self, event_uuid: uuid.UUID) -> None:
        await self.session.execute(
            delete(CompanyEvent).where(CompanyEvent.id == event_uuid)
        )

    async def register_for_event(self, event_uuid: uuid.UUID, user_uuid: uuid.UUID) -> EventRegistration:
        result = await self.session.execute(
            select(EventRegistration).where(
                and_(
                    EventRegistration.event_id == event_uuid,
                    EventRegistration.user_id == user_uuid,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        obj = EventRegistration(event_id=event_uuid, user_id=user_uuid)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Polls CRUD
    # ------------------------------------------------------------------

    async def create_poll(self, **kwargs: Any) -> Poll:
        obj = Poll(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def add_poll_option(self, poll_uuid: uuid.UUID, option_text: str) -> PollOption:
        obj = PollOption(poll_id=poll_uuid, option_text=option_text)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_poll_by_id(self, poll_uuid: uuid.UUID) -> Poll | None:
        result = await self.session.execute(
            select(Poll)
            .where(Poll.id == poll_uuid)
            .options(
                selectinload(Poll.options),
                selectinload(Poll.votes).selectinload(PollVote.option),
            )
        )
        return result.scalar_one_or_none()

    async def list_polls(self, status: str | None = None, limit: int = 50) -> list[Poll]:
        stmt = select(Poll).options(selectinload(Poll.options))
        if status:
            stmt = stmt.where(Poll.status == status.upper())
        stmt = stmt.order_by(Poll.end_date.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_poll(self, poll_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Poll).where(Poll.id == poll_uuid).values(**kwargs)
        )

    async def delete_poll(self, poll_uuid: uuid.UUID) -> None:
        await self.session.execute(
            delete(Poll).where(Poll.id == poll_uuid)
        )

    async def check_user_voted(self, poll_uuid: uuid.UUID, user_uuid: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(PollVote).where(
                and_(
                    PollVote.poll_id == poll_uuid,
                    PollVote.user_id == user_uuid,
                )
            )
        )
        return result.scalars().first() is not None

    async def cast_vote(self, poll_uuid: uuid.UUID, option_uuid: uuid.UUID, user_uuid: uuid.UUID | None = None) -> PollVote:
        obj = PollVote(poll_id=poll_uuid, option_id=option_uuid, user_id=user_uuid)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Notification & Audits
    # ------------------------------------------------------------------

    async def create_notification(self, **kwargs: Any) -> NotificationCenter:
        obj = NotificationCenter(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_audit_log(self, **kwargs: Any) -> CommunicationAuditLog:
        obj = CommunicationAuditLog(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj
