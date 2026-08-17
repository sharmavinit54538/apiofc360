"""Database repository for OFC360 Connect module."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
import uuid

from sqlalchemy import and_, delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException

from app.models.connect import (
    ConnectCallLog,
    ConnectChannel,
    ConnectChannelMember,
    ConnectConversation,
    ConnectConversationParticipant,
    ConnectMeeting,
    ConnectMeetingMessage,
    ConnectMeetingParticipant,
    ConnectMessage,
    ConnectMessageAttachment,
    ConnectMessageReaction,
    ConnectNotification,
    ConnectSharedFile,
    ConnectUserPresence,
    ConnectUserSoundSettings,
)
from app.models.department import Department
from app.models.employee import Employee
from app.models.user import User

logger = logging.getLogger(__name__)


class ConnectRepository:
    """SQLAlchemy repository for Connect domain entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # =========================================================================
    # A. User Discovery & Directory
    # =========================================================================

    async def get_colleagues(
        self,
        company_id: uuid.UUID,
        search: str | None = None,
        department: str | None = None,
        presence_filter: str | None = None,
        page: int = 1,
        limit: int = 20,
        exclude_user_id: uuid.UUID | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch colleagues within the tenant matching filters and search."""
        offset = (page - 1) * limit

        stmt = (
            select(User, Employee, ConnectUserPresence)
            .outerjoin(Employee, and_(Employee.user_id == User.id, Employee.is_deleted.is_(False)))
            .outerjoin(ConnectUserPresence, ConnectUserPresence.user_id == User.id)
            .where(
                User.company_id == company_id,
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
        )

        if exclude_user_id:
            stmt = stmt.where(User.id != exclude_user_id)

        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.name).like(term),
                    func.lower(User.email).like(term),
                    func.lower(Employee.designation).like(term),
                )
            )

        if department and department.strip():
            stmt = stmt.where(func.lower(Employee.department) == department.strip().lower())

        if presence_filter and presence_filter.strip():
            p_val = presence_filter.strip().lower()
            if p_val == "offline":
                stmt = stmt.where(
                    or_(
                        ConnectUserPresence.status == "offline",
                        ConnectUserPresence.status.is_(None),
                    )
                )
            else:
                stmt = stmt.where(func.lower(ConnectUserPresence.status) == p_val)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar() or 0

        # Paginated results
        stmt = stmt.order_by(User.name.asc()).offset(offset).limit(limit)
        results = await self.session.execute(stmt)
        rows = results.all()

        colleagues = []
        for user, emp, pres in rows:
            avatar = (
                getattr(user, "profile_photo_url", None)
                or getattr(user, "profile_photo", None)
                or (emp.profile_photo_url if emp else None)
                or (getattr(emp, "avatar_url", None) if emp else None)
            )
            colleagues.append({
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "phone": getattr(user, "phone", None),
                "role": getattr(user.role, "value", str(user.role)) if user.role else "employee",
                "department": emp.department if emp else None,
                "designation": emp.designation if emp else None,
                "avatar_url": avatar,
                "presence_status": pres.status if pres else "offline",
                "custom_status": pres.custom_status if pres else None,
                "last_seen_at": pres.last_seen_at if pres else user.created_at,
            })

        return colleagues, total

    async def unified_search(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Perform unified search across people, channels, messages, and files in company."""
        term = f"%{query.strip().lower()}%"

        # 1. People
        people_colleagues, _ = await self.get_colleagues(
            company_id=company_id,
            search=query,
            page=1,
            limit=limit,
        )

        # 2. Channels (Public channels or private channels user is member of)
        user_chan_ids_res = await self.session.execute(
            select(ConnectChannelMember.channel_id).where(
                ConnectChannelMember.user_id == user_id,
                ConnectChannelMember.company_id == company_id,
            )
        )
        user_chan_ids = set(user_chan_ids_res.scalars().all())

        chan_stmt = (
            select(ConnectChannel)
            .where(
                ConnectChannel.company_id == company_id,
                ConnectChannel.is_deleted.is_(False),
                or_(
                    func.lower(ConnectChannel.name).like(term),
                    func.lower(ConnectChannel.description).like(term),
                ),
                or_(
                    ConnectChannel.is_private.is_(False),
                    ConnectChannel.id.in_(user_chan_ids) if user_chan_ids else False,
                )
            )
            .limit(limit)
        )
        chan_rows = (await self.session.execute(chan_stmt)).scalars().all()
        channels = [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "is_private": c.is_private,
                "members_count": len(c.members),
            }
            for c in chan_rows
        ]

        # 3. Messages (in user's conversations or accessible channels)
        conv_ids_res = await self.session.execute(
            select(ConnectConversationParticipant.conversation_id).where(
                ConnectConversationParticipant.user_id == user_id,
                ConnectConversationParticipant.company_id == company_id,
            )
        )
        user_conv_ids = set(conv_ids_res.scalars().all())

        msg_filter = []
        if user_conv_ids:
            msg_filter.append(ConnectMessage.conversation_id.in_(user_conv_ids))
        if user_chan_ids:
            msg_filter.append(ConnectMessage.channel_id.in_(user_chan_ids))

        messages = []
        if msg_filter:
            msg_stmt = (
                select(ConnectMessage, User.name)
                .join(User, User.id == ConnectMessage.sender_id)
                .where(
                    ConnectMessage.company_id == company_id,
                    ConnectMessage.is_deleted.is_(False),
                    func.lower(ConnectMessage.content).like(term),
                    or_(*msg_filter),
                )
                .order_by(ConnectMessage.created_at.desc())
                .limit(limit)
            )
            msg_rows = (await self.session.execute(msg_stmt)).all()
            for msg, sender_name in msg_rows:
                messages.append({
                    "id": msg.id,
                    "conversation_id": msg.conversation_id,
                    "channel_id": msg.channel_id,
                    "sender_id": msg.sender_id,
                    "sender_name": sender_name,
                    "content": msg.content,
                    "created_at": msg.created_at,
                })

        # 4. Files
        file_stmt = (
            select(ConnectSharedFile, User.name)
            .join(User, User.id == ConnectSharedFile.uploader_id)
            .where(
                ConnectSharedFile.company_id == company_id,
                ConnectSharedFile.is_deleted.is_(False),
                func.lower(ConnectSharedFile.file_name).like(term),
            )
            .order_by(ConnectSharedFile.created_at.desc())
            .limit(limit)
        )
        file_rows = (await self.session.execute(file_stmt)).all()
        files = [
            {
                "id": f.id,
                "file_name": f.file_name,
                "file_url": f.file_url,
                "file_type": f.file_type,
                "file_size": f.file_size,
                "uploader_name": uploader_name,
                "created_at": f.created_at,
            }
            for f, uploader_name in file_rows
        ]

        return {
            "people": people_colleagues,
            "channels": channels,
            "messages": messages,
            "files": files,
        }

    # =========================================================================
    # B. Direct Messaging & Conversations
    # =========================================================================

    async def get_user_conversations(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[ConnectConversation]:
        """Get all DM conversations for user with participants and unread counts."""
        # Find conversation IDs where user is participant
        conv_ids_stmt = select(ConnectConversationParticipant.conversation_id).where(
            ConnectConversationParticipant.user_id == user_id,
            ConnectConversationParticipant.company_id == company_id,
            ConnectConversationParticipant.is_archived.is_(False),
        )
        conv_ids_res = await self.session.execute(conv_ids_stmt)
        conv_ids = conv_ids_res.scalars().all()

        if not conv_ids:
            return []

        stmt = (
            select(ConnectConversation)
            .options(
                selectinload(ConnectConversation.participants).selectinload(ConnectConversationParticipant.user)
            )
            .where(
                ConnectConversation.id.in_(conv_ids),
                ConnectConversation.company_id == company_id,
                ConnectConversation.is_deleted.is_(False),
            )
            .order_by(ConnectConversation.last_message_at.desc().nullslast(), ConnectConversation.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_or_create_dm_conversation(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> tuple[ConnectConversation, bool]:
        """Find an existing DM conversation between two users or create a new one idempotently."""
        # Query for existing conversation having both participants
        p1 = select(ConnectConversationParticipant.conversation_id).where(
            ConnectConversationParticipant.user_id == user_id,
            ConnectConversationParticipant.company_id == company_id,
        )
        p2 = select(ConnectConversationParticipant.conversation_id).where(
            ConnectConversationParticipant.user_id == target_user_id,
            ConnectConversationParticipant.company_id == company_id,
        )
        shared_conv_ids_stmt = select(ConnectConversation.id).where(
            ConnectConversation.id.in_(p1),
            ConnectConversation.id.in_(p2),
            ConnectConversation.company_id == company_id,
            ConnectConversation.is_deleted.is_(False),
        )
        shared_res = await self.session.execute(shared_conv_ids_stmt)
        existing_conv_id = shared_res.scalars().first()

        if existing_conv_id:
            conv = await self.get_conversation_by_id(existing_conv_id, company_id)
            if conv:
                return conv, False

        # Create new conversation
        conv = ConnectConversation(
            company_id=company_id,
            created_by=user_id,
        )
        self.session.add(conv)
        await self.session.flush()

        # Add both participants
        participant1 = ConnectConversationParticipant(
            conversation_id=conv.id,
            user_id=user_id,
            company_id=company_id,
        )
        participant2 = ConnectConversationParticipant(
            conversation_id=conv.id,
            user_id=target_user_id,
            company_id=company_id,
        )
        self.session.add_all([participant1, participant2])
        await self.session.commit()

        # Reload with relations
        reloaded = await self.get_conversation_by_id(conv.id, company_id)
        return reloaded, True

    async def get_conversation_by_id(
        self,
        conversation_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectConversation | None:
        """Fetch conversation with participants eager loaded."""
        stmt = (
            select(ConnectConversation)
            .options(
                selectinload(ConnectConversation.participants).selectinload(ConnectConversationParticipant.user)
            )
            .where(
                ConnectConversation.id == conversation_id,
                ConnectConversation.company_id == company_id,
                ConnectConversation.is_deleted.is_(False),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def is_user_in_conversation(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> bool:
        """Verify user is a registered participant of the conversation."""
        stmt = select(ConnectConversationParticipant.id).where(
            ConnectConversationParticipant.conversation_id == conversation_id,
            ConnectConversationParticipant.user_id == user_id,
            ConnectConversationParticipant.company_id == company_id,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none() is not None

    async def get_conversation_messages(
        self,
        conversation_id: uuid.UUID,
        company_id: uuid.UUID,
        query: str | None = None,
        before_id: uuid.UUID | None = None,
        after_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[ConnectMessage]:
        """Fetch messages inside a conversation with cursor pagination, reactions, and attachments."""
        stmt = (
            select(ConnectMessage)
            .options(
                selectinload(ConnectMessage.sender),
                selectinload(ConnectMessage.reactions).selectinload(ConnectMessageReaction.user),
                selectinload(ConnectMessage.attachments),
            )
            .where(
                ConnectMessage.conversation_id == conversation_id,
                ConnectMessage.company_id == company_id,
                ConnectMessage.parent_message_id.is_(None),  # Top-level messages
                ConnectMessage.is_deleted.is_(False),
            )
        )

        if query and query.strip():
            stmt = stmt.where(func.lower(ConnectMessage.content).like(f"%{query.strip().lower()}%"))

        if before_id:
            # Get created_at of before_id message
            before_msg = await self.session.get(ConnectMessage, before_id)
            if before_msg:
                stmt = stmt.where(ConnectMessage.created_at < before_msg.created_at)
        elif after_id:
            after_msg = await self.session.get(ConnectMessage, after_id)
            if after_msg:
                stmt = stmt.where(ConnectMessage.created_at > after_msg.created_at)

        stmt = stmt.order_by(ConnectMessage.created_at.desc()).limit(limit)
        res = await self.session.execute(stmt)
        messages = list(res.scalars().all())
        # Return in ascending chronological order for chat UI
        messages.reverse()
        return messages

    async def create_message(
        self,
        company_id: uuid.UUID,
        sender_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        channel_id: uuid.UUID | None = None,
        content: str | None = None,
        voice_url: str | None = None,
        voice_duration: int | None = None,
        reply_to_id: uuid.UUID | None = None,
        parent_message_id: uuid.UUID | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> ConnectMessage:
        """Create and persist a message with attachments."""
        msg = ConnectMessage(
            company_id=company_id,
            sender_id=sender_id,
            conversation_id=conversation_id,
            channel_id=channel_id,
            content=content,
            voice_url=voice_url,
            voice_duration=voice_duration,
            reply_to_id=reply_to_id,
            parent_message_id=parent_message_id,
        )
        self.session.add(msg)
        await self.session.flush()

        if attachments:
            for att in attachments:
                att_obj = ConnectMessageAttachment(
                    message_id=msg.id,
                    company_id=company_id,
                    file_name=att.get("fileName", "attachment"),
                    file_url=att.get("fileUrl", ""),
                    file_type=att.get("fileType", "application/octet-stream"),
                    file_size=att.get("fileSize", 0),
                )
                self.session.add(att_obj)

        # Update conversation last message preview & timestamp
        if conversation_id:
            preview = content[:200] if content else ("[Voice Message]" if voice_url else "[Attachment]")
            await self.session.execute(
                update(ConnectConversation)
                .where(ConnectConversation.id == conversation_id)
                .values(
                    last_message_at=func.now(),
                    last_message_preview=preview,
                    updated_at=func.now(),
                )
            )

        await self.session.commit()
        return await self.get_message_by_id(msg.id, company_id)

    async def get_message_by_id(
        self,
        message_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectMessage | None:
        """Fetch single message with all relationships."""
        stmt = (
            select(ConnectMessage)
            .options(
                selectinload(ConnectMessage.sender),
                selectinload(ConnectMessage.reactions).selectinload(ConnectMessageReaction.user),
                selectinload(ConnectMessage.attachments),
            )
            .where(
                ConnectMessage.id == message_id,
                ConnectMessage.company_id == company_id,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def toggle_message_reaction(
        self,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        emoji: str,
    ) -> tuple[ConnectMessageReaction | None, bool]:
        """Toggle reaction: delete if exists, otherwise create. Returns (reaction, is_added)."""
        stmt = select(ConnectMessageReaction).where(
            ConnectMessageReaction.message_id == message_id,
            ConnectMessageReaction.user_id == user_id,
            ConnectMessageReaction.company_id == company_id,
            ConnectMessageReaction.emoji == emoji,
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            await self.session.delete(existing)
            await self.session.commit()
            return None, False

        reaction = ConnectMessageReaction(
            message_id=message_id,
            user_id=user_id,
            company_id=company_id,
            emoji=emoji,
        )
        self.session.add(reaction)
        await self.session.commit()
        await self.session.refresh(reaction)
        return reaction, True

    async def toggle_message_pin(
        self,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        is_pinned: bool,
    ) -> ConnectMessage:
        """Pin or unpin a message."""
        msg = await self.get_message_by_id(message_id, company_id)
        if not msg:
            raise NotFoundException("Message not found.")

        msg.is_pinned = is_pinned
        msg.pinned_at = func.now() if is_pinned else None
        msg.pinned_by = user_id if is_pinned else None
        await self.session.commit()
        return await self.get_message_by_id(message_id, company_id)

    async def soft_delete_message(
        self,
        message_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> None:
        """Soft delete a message."""
        await self.session.execute(
            update(ConnectMessage)
            .where(
                ConnectMessage.id == message_id,
                ConnectMessage.company_id == company_id,
            )
            .values(
                is_deleted=True,
                deleted_at=func.now(),
            )
        )
        await self.session.commit()

    async def get_thread_messages(
        self,
        parent_message_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> list[ConnectMessage]:
        """Fetch all thread replies for a parent message."""
        stmt = (
            select(ConnectMessage)
            .options(
                selectinload(ConnectMessage.sender),
                selectinload(ConnectMessage.reactions).selectinload(ConnectMessageReaction.user),
                selectinload(ConnectMessage.attachments),
            )
            .where(
                ConnectMessage.parent_message_id == parent_message_id,
                ConnectMessage.company_id == company_id,
                ConnectMessage.is_deleted.is_(False),
            )
            .order_by(ConnectMessage.created_at.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # =========================================================================
    # C. Team Channels
    # =========================================================================

    async def get_channels(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str | None = None,
    ) -> list[ConnectChannel]:
        """Fetch all public channels and private channels the user belongs to."""
        # Find private channels user is member of
        user_chan_ids_res = await self.session.execute(
            select(ConnectChannelMember.channel_id).where(
                ConnectChannelMember.user_id == user_id,
                ConnectChannelMember.company_id == company_id,
            )
        )
        user_chan_ids = set(user_chan_ids_res.scalars().all())

        stmt = (
            select(ConnectChannel)
            .options(
                selectinload(ConnectChannel.members).selectinload(ConnectChannelMember.user),
                selectinload(ConnectChannel.creator),
            )
            .where(
                ConnectChannel.company_id == company_id,
                ConnectChannel.is_deleted.is_(False),
                or_(
                    ConnectChannel.is_private.is_(False),
                    ConnectChannel.id.in_(user_chan_ids) if user_chan_ids else False,
                )
            )
        )

        if query and query.strip():
            stmt = stmt.where(func.lower(ConnectChannel.name).like(f"%{query.strip().lower()}%"))

        stmt = stmt.order_by(ConnectChannel.name.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_channel(
        self,
        company_id: uuid.UUID,
        creator_id: uuid.UUID,
        name: str,
        description: str | None = None,
        is_private: bool = False,
        member_ids: list[uuid.UUID] | None = None,
    ) -> ConnectChannel:
        """Create team channel, assign creator as host, and add initial members with tenant isolation."""
        channel = ConnectChannel(
            company_id=company_id,
            name=name,
            description=description,
            is_private=is_private,
            created_by=creator_id,
        )
        self.session.add(channel)
        await self.session.flush()

        # Add creator as host
        host_member = ConnectChannelMember(
            channel_id=channel.id,
            user_id=creator_id,
            company_id=company_id,
            role="host",
        )
        self.session.add(host_member)

        # Add other initial members with company tenant filtering and deduplication
        added_members = {creator_id}
        if member_ids:
            valid_res = await self.session.execute(
                select(User.id).where(
                    User.id.in_(member_ids),
                    User.company_id == company_id,
                    User.is_active.is_(True),
                    User.is_deleted.is_(False),
                )
            )
            valid_ids = set(valid_res.scalars().all())
            for m_id in valid_ids:
                if m_id not in added_members:
                    self.session.add(
                        ConnectChannelMember(
                            channel_id=channel.id,
                            user_id=m_id,
                            company_id=company_id,
                            role="member",
                        )
                    )
                    added_members.add(m_id)

        await self.session.commit()
        return await self.get_channel_by_id(channel.id, company_id)

    async def get_channel_by_id(
        self,
        channel_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectChannel | None:
        """Fetch channel with members and creator eager loaded."""
        stmt = (
            select(ConnectChannel)
            .options(
                selectinload(ConnectChannel.members).selectinload(ConnectChannelMember.user),
                selectinload(ConnectChannel.creator),
            )
            .where(
                ConnectChannel.id == channel_id,
                ConnectChannel.company_id == company_id,
                ConnectChannel.is_deleted.is_(False),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_channel(
        self,
        channel_id: uuid.UUID,
        company_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        is_private: bool | None = None,
        is_archived: bool | None = None,
    ) -> ConnectChannel | None:
        """Update channel details."""
        values: dict[str, Any] = {"updated_at": func.now()}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if is_private is not None:
            values["is_private"] = is_private
        if is_archived is not None:
            values["is_archived"] = is_archived

        await self.session.execute(
            update(ConnectChannel)
            .where(
                ConnectChannel.id == channel_id,
                ConnectChannel.company_id == company_id,
                ConnectChannel.is_deleted.is_(False),
            )
            .values(**values)
        )
        await self.session.commit()
        return await self.get_channel_by_id(channel_id, company_id)

    async def soft_delete_channel(
        self,
        channel_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> None:
        """Soft delete a channel."""
        await self.session.execute(
            update(ConnectChannel)
            .where(
                ConnectChannel.id == channel_id,
                ConnectChannel.company_id == company_id,
                ConnectChannel.is_deleted.is_(False),
            )
            .values(is_deleted=True, deleted_at=func.now(), updated_at=func.now())
        )
        await self.session.commit()

    async def add_channel_members(
        self,
        channel_id: uuid.UUID,
        company_id: uuid.UUID,
        user_ids: list[uuid.UUID],
        role: str = "member",
    ) -> ConnectChannel | None:
        """Add members to a channel with company tenant isolation and duplicate prevention."""
        if not user_ids:
            return await self.get_channel_by_id(channel_id, company_id)

        # 1. Fetch valid active company users
        valid_users_res = await self.session.execute(
            select(User.id).where(
                User.id.in_(user_ids),
                User.company_id == company_id,
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
        )
        valid_user_ids = set(valid_users_res.scalars().all())

        # 2. Fetch existing channel members to avoid unique constraint violations
        existing_res = await self.session.execute(
            select(ConnectChannelMember.user_id).where(
                ConnectChannelMember.channel_id == channel_id,
                ConnectChannelMember.company_id == company_id,
            )
        )
        existing_user_ids = set(existing_res.scalars().all())

        new_members = []
        for uid in valid_user_ids:
            if uid not in existing_user_ids:
                new_members.append(
                    ConnectChannelMember(
                        channel_id=channel_id,
                        user_id=uid,
                        company_id=company_id,
                        role=role,
                    )
                )

        if new_members:
            self.session.add_all(new_members)
            await self.session.commit()

        return await self.get_channel_by_id(channel_id, company_id)

    async def get_channel_messages(
        self,
        channel_id: uuid.UUID,
        company_id: uuid.UUID,
        query: str | None = None,
        pinned_only: bool = False,
        before_id: uuid.UUID | None = None,
        after_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[ConnectMessage]:
        """Fetch messages inside a channel with search and pinning support."""
        stmt = (
            select(ConnectMessage)
            .options(
                selectinload(ConnectMessage.sender),
                selectinload(ConnectMessage.reactions).selectinload(ConnectMessageReaction.user),
                selectinload(ConnectMessage.attachments),
            )
            .where(
                ConnectMessage.channel_id == channel_id,
                ConnectMessage.company_id == company_id,
                ConnectMessage.parent_message_id.is_(None),
                ConnectMessage.is_deleted.is_(False),
            )
        )

        if pinned_only:
            stmt = stmt.where(ConnectMessage.is_pinned.is_(True))

        if query and query.strip():
            stmt = stmt.where(func.lower(ConnectMessage.content).like(f"%{query.strip().lower()}%"))

        if before_id:
            before_msg = await self.session.get(ConnectMessage, before_id)
            if before_msg:
                stmt = stmt.where(ConnectMessage.created_at < before_msg.created_at)
        elif after_id:
            after_msg = await self.session.get(ConnectMessage, after_id)
            if after_msg:
                stmt = stmt.where(ConnectMessage.created_at > after_msg.created_at)

        stmt = stmt.order_by(ConnectMessage.created_at.desc()).limit(limit)
        res = await self.session.execute(stmt)
        messages = list(res.scalars().all())
        messages.reverse()
        return messages

    async def remove_channel_member(
        self,
        channel_id: uuid.UUID,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> None:
        """Remove user from a channel."""
        await self.session.execute(
            delete(ConnectChannelMember).where(
                ConnectChannelMember.channel_id == channel_id,
                ConnectChannelMember.user_id == user_id,
                ConnectChannelMember.company_id == company_id,
            )
        )
        await self.session.commit()

    async def archive_channel(
        self,
        channel_id: uuid.UUID,
        company_id: uuid.UUID,
        is_archived: bool = True,
    ) -> ConnectChannel | None:
        """Archive or unarchive a channel."""
        await self.session.execute(
            update(ConnectChannel)
            .where(
                ConnectChannel.id == channel_id,
                ConnectChannel.company_id == company_id,
                ConnectChannel.is_deleted.is_(False),
            )
            .values(is_archived=is_archived, updated_at=func.now())
        )
        await self.session.commit()
        return await self.get_channel_by_id(channel_id, company_id)

    # =========================================================================
    # D. Calls & WebRTC
    # =========================================================================

    async def get_call_history(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int = 50,
    ) -> list[ConnectCallLog]:
        """Fetch user's call logs in descending order."""
        stmt = (
            select(ConnectCallLog)
            .options(
                selectinload(ConnectCallLog.caller),
                selectinload(ConnectCallLog.callee),
            )
            .where(
                ConnectCallLog.company_id == company_id,
                or_(
                    ConnectCallLog.caller_id == user_id,
                    ConnectCallLog.callee_id == user_id,
                ),
            )
            .order_by(ConnectCallLog.created_at.desc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_call_log(
        self,
        company_id: uuid.UUID,
        caller_id: uuid.UUID,
        callee_id: uuid.UUID,
        call_type: str,
        room_id: str,
    ) -> ConnectCallLog:
        """Initiate and log a new call session."""
        call = ConnectCallLog(
            company_id=company_id,
            caller_id=caller_id,
            callee_id=callee_id,
            call_type=call_type,
            status="initiated",
            room_id=room_id,
        )
        self.session.add(call)
        await self.session.commit()
        await self.session.refresh(call)
        return call

    async def get_call_by_id(
        self,
        call_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectCallLog | None:
        """Fetch call log by ID."""
        stmt = (
            select(ConnectCallLog)
            .options(
                selectinload(ConnectCallLog.caller),
                selectinload(ConnectCallLog.callee),
            )
            .where(
                ConnectCallLog.id == call_id,
                ConnectCallLog.company_id == company_id,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_call_status(
        self,
        call_id: uuid.UUID,
        company_id: uuid.UUID,
        status: str,
    ) -> ConnectCallLog:
        """Update status and timestamps for a call session."""
        call = await self.get_call_by_id(call_id, company_id)
        if not call:
            raise NotFoundException("Call not found.")

        call.status = status
        if status == "connected" and not call.connected_at:
            call.connected_at = datetime.utcnow()
        elif status in ("ended", "rejected", "missed", "failed") and not call.ended_at:
            call.ended_at = datetime.utcnow()
            if call.connected_at:
                call.duration_seconds = int((call.ended_at - call.connected_at).total_seconds())

        await self.session.commit()
        return call

    async def get_active_user_in_company(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> User | None:
        """Fetch active non-deleted user belonging to company."""
        stmt = select(User).where(
            User.id == user_id,
            User.company_id == company_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()


    # =========================================================================
    # E. Video Meetings
    # =========================================================================

    async def get_user_meetings(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        status_filter: str | None = None,
    ) -> list[ConnectMeeting]:
        """Fetch video meetings hosted by or inviting the user."""
        participant_m_ids = select(ConnectMeetingParticipant.meeting_id).where(
            ConnectMeetingParticipant.user_id == user_id,
            ConnectMeetingParticipant.company_id == company_id,
        )

        stmt = (
            select(ConnectMeeting)
            .options(
                selectinload(ConnectMeeting.host),
                selectinload(ConnectMeeting.participants).selectinload(ConnectMeetingParticipant.user),
            )
            .where(
                ConnectMeeting.company_id == company_id,
                or_(
                    ConnectMeeting.host_id == user_id,
                    ConnectMeeting.id.in_(participant_m_ids),
                ),
            )
        )

        if status_filter:
            stmt = stmt.where(ConnectMeeting.status == status_filter)

        stmt = stmt.order_by(ConnectMeeting.start_time.desc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_meeting(
        self,
        company_id: uuid.UUID,
        host_id: uuid.UUID,
        title: str,
        meeting_code: str,
        description: str | None = None,
        meeting_type: str = "instant",
        start_time: datetime | None = None,
        duration_minutes: int = 30,
        participant_ids: list[uuid.UUID] | None = None,
        allow_screen_share: bool = True,
        allow_microphone: bool = True,
        allow_camera: bool = True,
        is_private: bool = False,
    ) -> ConnectMeeting:
        """Create new video meeting and register participants."""
        meeting = ConnectMeeting(
            company_id=company_id,
            host_id=host_id,
            title=title,
            description=description,
            meeting_code=meeting_code,
            meeting_type=meeting_type,
            status="live" if meeting_type == "instant" else "scheduled",
            start_time=start_time or datetime.utcnow(),
            duration_minutes=duration_minutes,
            allow_screen_share=allow_screen_share,
            allow_microphone=allow_microphone,
            allow_camera=allow_camera,
            is_private=is_private,
        )
        self.session.add(meeting)
        await self.session.flush()

        # Add host as participant
        host_part = ConnectMeetingParticipant(
            meeting_id=meeting.id,
            user_id=host_id,
            company_id=company_id,
            role="host",
            status="joined" if meeting_type == "instant" else "invited",
            joined_at=datetime.utcnow() if meeting_type == "instant" else None,
        )
        self.session.add(host_part)

        # Add invited participants
        added = {host_id}
        if participant_ids:
            for pid in participant_ids:
                if pid not in added:
                    self.session.add(
                        ConnectMeetingParticipant(
                            meeting_id=meeting.id,
                            user_id=pid,
                            company_id=company_id,
                            role="participant",
                            status="invited",
                        )
                    )
                    added.add(pid)

        await self.session.commit()
        return await self.get_meeting_by_id(meeting.id, company_id)

    async def get_meeting_by_id(
        self,
        meeting_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectMeeting | None:
        """Fetch meeting by ID with host and participants."""
        stmt = (
            select(ConnectMeeting)
            .options(
                selectinload(ConnectMeeting.host),
                selectinload(ConnectMeeting.participants).selectinload(ConnectMeetingParticipant.user),
            )
            .where(
                ConnectMeeting.id == meeting_id,
                ConnectMeeting.company_id == company_id,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_meeting_by_code(
        self,
        meeting_code: str,
        company_id: uuid.UUID,
    ) -> ConnectMeeting | None:
        """Fetch meeting by unique meeting code."""
        stmt = (
            select(ConnectMeeting)
            .options(
                selectinload(ConnectMeeting.host),
                selectinload(ConnectMeeting.participants).selectinload(ConnectMeetingParticipant.user),
            )
            .where(
                ConnectMeeting.meeting_code == meeting_code,
                ConnectMeeting.company_id == company_id,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def join_meeting(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectMeetingParticipant:
        """Register user as active joined participant in a meeting."""
        stmt = select(ConnectMeetingParticipant).where(
            ConnectMeetingParticipant.meeting_id == meeting_id,
            ConnectMeetingParticipant.user_id == user_id,
            ConnectMeetingParticipant.company_id == company_id,
        )
        res = await self.session.execute(stmt)
        participant = res.scalar_one_or_none()

        if not participant:
            participant = ConnectMeetingParticipant(
                meeting_id=meeting_id,
                user_id=user_id,
                company_id=company_id,
                role="participant",
                status="joined",
                joined_at=datetime.utcnow(),
            )
            self.session.add(participant)
        else:
            participant.status = "joined"
            participant.joined_at = datetime.utcnow()
            participant.left_at = None

        await self.session.commit()
        await self.session.refresh(participant)
        return participant

    async def leave_meeting(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        end_for_everyone: bool = False,
    ) -> ConnectMeeting:
        """Mark participant as left or end meeting for all."""
        meeting = await self.get_meeting_by_id(meeting_id, company_id)
        if not meeting:
            raise NotFoundException("Meeting not found.")

        if end_for_everyone:
            meeting.status = "ended"
            meeting.end_time = datetime.utcnow()
            await self.session.execute(
                update(ConnectMeetingParticipant)
                .where(ConnectMeetingParticipant.meeting_id == meeting_id)
                .values(status="left", left_at=datetime.utcnow())
            )
        else:
            await self.session.execute(
                update(ConnectMeetingParticipant)
                .where(
                    ConnectMeetingParticipant.meeting_id == meeting_id,
                    ConnectMeetingParticipant.user_id == user_id,
                )
                .values(status="left", left_at=datetime.utcnow())
            )

        await self.session.commit()
        return await self.get_meeting_by_id(meeting_id, company_id)

    async def add_meeting_message(
        self,
        meeting_id: uuid.UUID,
        sender_id: uuid.UUID,
        company_id: uuid.UUID,
        content: str,
    ) -> ConnectMeetingMessage:
        """Store in-meeting chat message."""
        msg = ConnectMeetingMessage(
            meeting_id=meeting_id,
            sender_id=sender_id,
            company_id=company_id,
            content=content,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    # =========================================================================
    # F. Shared Files
    # =========================================================================

    async def get_shared_files(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        filter_type: str = "all",
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ConnectSharedFile], int]:
        """Fetch shared files with filtering by category, ownership, and search."""
        offset = (page - 1) * limit
        stmt = (
            select(ConnectSharedFile)
            .options(selectinload(ConnectSharedFile.uploader))
            .where(
                ConnectSharedFile.company_id == company_id,
                ConnectSharedFile.is_deleted.is_(False),
            )
        )

        if filter_type == "shared_by_me":
            stmt = stmt.where(ConnectSharedFile.uploader_id == user_id)
        elif filter_type in ("images", "videos", "documents", "spreadsheets"):
            stmt = stmt.where(ConnectSharedFile.file_category == filter_type)

        if search and search.strip():
            stmt = stmt.where(func.lower(ConnectSharedFile.file_name).like(f"%{search.strip().lower()}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar() or 0

        stmt = stmt.order_by(ConnectSharedFile.created_at.desc()).offset(offset).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), total

    async def create_shared_file(
        self,
        company_id: uuid.UUID,
        uploader_id: uuid.UUID,
        file_name: str,
        file_url: str,
        file_path: str,
        file_type: str,
        file_category: str,
        file_size: int,
    ) -> ConnectSharedFile:
        """Create shared file record."""
        shared_file = ConnectSharedFile(
            company_id=company_id,
            uploader_id=uploader_id,
            file_name=file_name,
            file_url=file_url,
            file_path=file_path,
            file_type=file_type,
            file_category=file_category,
            file_size=file_size,
        )
        self.session.add(shared_file)
        await self.session.commit()
        await self.session.refresh(shared_file)
        return shared_file

    async def get_shared_file_by_id(
        self,
        file_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectSharedFile | None:
        """Fetch shared file by ID."""
        stmt = select(ConnectSharedFile).where(
            ConnectSharedFile.id == file_id,
            ConnectSharedFile.company_id == company_id,
            ConnectSharedFile.is_deleted.is_(False),
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def delete_shared_file(
        self,
        file_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> None:
        """Soft delete shared file record."""
        await self.session.execute(
            update(ConnectSharedFile)
            .where(
                ConnectSharedFile.id == file_id,
                ConnectSharedFile.company_id == company_id,
            )
            .values(is_deleted=True, deleted_at=func.now())
        )
        await self.session.commit()

    # =========================================================================
    # G. Presence
    # =========================================================================

    async def upsert_presence(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        status: str,
        custom_status: str | None = None,
    ) -> ConnectUserPresence:
        """Upsert presence status and timestamp for a user."""
        stmt = select(ConnectUserPresence).where(
            ConnectUserPresence.user_id == user_id,
            ConnectUserPresence.company_id == company_id,
        )
        res = await self.session.execute(stmt)
        pres = res.scalar_one_or_none()

        if pres:
            pres.status = status
            pres.custom_status = custom_status
            pres.last_seen_at = func.now()
            pres.updated_at = func.now()
        else:
            pres = ConnectUserPresence(
                user_id=user_id,
                company_id=company_id,
                status=status,
                custom_status=custom_status,
            )
            self.session.add(pres)

        await self.session.commit()
        await self.session.refresh(pres)
        return pres

    async def get_batch_presence(
        self,
        user_ids: list[uuid.UUID],
        company_id: uuid.UUID,
    ) -> list[ConnectUserPresence]:
        """Fetch presence records for multiple users."""
        if not user_ids:
            return []
        stmt = select(ConnectUserPresence).where(
            ConnectUserPresence.user_id.in_(user_ids),
            ConnectUserPresence.company_id == company_id,
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # =========================================================================
    # H. Notifications
    # =========================================================================

    async def get_notifications(
        self,
        recipient_id: uuid.UUID,
        company_id: uuid.UUID,
        unread_only: bool = False,
        limit: int = 50,
        notification_type: str | None = None,
    ) -> list[ConnectNotification]:
        """Fetch notifications for user."""
        stmt = (
            select(ConnectNotification)
            .options(selectinload(ConnectNotification.sender))
            .where(
                ConnectNotification.recipient_id == recipient_id,
                ConnectNotification.company_id == company_id,
            )
        )

        if unread_only:
            stmt = stmt.where(ConnectNotification.is_read.is_(False))

        if notification_type:
            stmt = stmt.where(ConnectNotification.notification_type == notification_type)

        stmt = stmt.order_by(ConnectNotification.created_at.desc()).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_notification(
        self,
        company_id: uuid.UUID,
        recipient_id: uuid.UUID,
        sender_id: uuid.UUID | None,
        notification_type: str,
        title: str,
        body: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> ConnectNotification:
        """Create a notification record."""
        notif = ConnectNotification(
            company_id=company_id,
            recipient_id=recipient_id,
            sender_id=sender_id,
            notification_type=notification_type,
            title=title,
            body=body,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        self.session.add(notif)
        await self.session.commit()
        await self.session.refresh(notif)
        return notif

    async def mark_notification_read(
        self,
        notification_id: uuid.UUID,
        recipient_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectNotification | None:
        """Mark notification as read."""
        stmt = select(ConnectNotification).where(
            ConnectNotification.id == notification_id,
            ConnectNotification.recipient_id == recipient_id,
            ConnectNotification.company_id == company_id,
        )
        res = await self.session.execute(stmt)
        notif = res.scalar_one_or_none()

        if notif:
            notif.is_read = True
            notif.read_at = datetime.utcnow()
            await self.session.commit()
            await self.session.refresh(notif)

        return notif

    async def delete_user_notifications(
        self,
        recipient_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> None:
        """Clear all notifications for user."""
        await self.session.execute(
            delete(ConnectNotification).where(
                ConnectNotification.recipient_id == recipient_id,
                ConnectNotification.company_id == company_id,
            )
        )
        await self.session.commit()

    # =========================================================================
    # I. Sound Settings
    # =========================================================================

    async def get_sound_settings(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> ConnectUserSoundSettings | None:
        """Fetch sound settings for user."""
        stmt = select(ConnectUserSoundSettings).where(
            ConnectUserSoundSettings.user_id == user_id,
            ConnectUserSoundSettings.company_id == company_id,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def upsert_sound_settings(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID,
        master_volume: int = 80,
        is_muted: bool = False,
        incoming_call_chime: bool = True,
        outgoing_call_chime: bool = True,
        message_chime: bool = True,
        mention_chime: bool = True,
        meeting_chime: bool = True,
        ringtone: str = "aurix_default_ringtone.mp3",
        notification_tone: str = "aurix_default_notification.mp3",
    ) -> ConnectUserSoundSettings:
        """Save audio settings for user."""
        settings = await self.get_sound_settings(user_id, company_id)
        if settings:
            settings.master_volume = master_volume
            settings.is_muted = is_muted
            settings.incoming_call_chime = incoming_call_chime
            settings.outgoing_call_chime = outgoing_call_chime
            settings.message_chime = message_chime
            settings.mention_chime = mention_chime
            settings.meeting_chime = meeting_chime
            settings.ringtone = ringtone
            settings.notification_tone = notification_tone
            settings.updated_at = func.now()
        else:
            settings = ConnectUserSoundSettings(
                user_id=user_id,
                company_id=company_id,
                master_volume=master_volume,
                is_muted=is_muted,
                incoming_call_chime=incoming_call_chime,
                outgoing_call_chime=outgoing_call_chime,
                message_chime=message_chime,
                mention_chime=mention_chime,
                meeting_chime=meeting_chime,
                ringtone=ringtone,
                notification_tone=notification_tone,
            )
            self.session.add(settings)

        await self.session.commit()
        await self.session.refresh(settings)
        return settings
