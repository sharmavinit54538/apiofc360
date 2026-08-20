"""Business logic service for OFC360 Connect module."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any
import uuid

from fastapi import UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.models.connect import (
    ConnectCallLog,
    ConnectChannel,
    ConnectConversation,
    ConnectMeeting,
    ConnectMessage,
    ConnectSharedFile,
    ConnectUserPresence,
    ConnectUserSoundSettings,
)
from app.models.user import User
from app.repositories.connect_repository import ConnectRepository
from app.services.connect_ai_service import ConnectAIService, get_connect_ai_service
from app.services.connect_ws_manager import ConnectWSManager, get_connect_ws_manager
from app.services.email_service import EmailService, get_email_service
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

# Allowed file extensions for shared files upload
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".avi",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".zip", ".tar", ".gz",
}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class ConnectService:
    """Connect domain service handling all business logic and permissions."""

    def __init__(
        self,
        session: AsyncSession,
        repo: ConnectRepository | None = None,
        ws_manager: ConnectWSManager | None = None,
        ai_service: ConnectAIService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        self.session = session
        self.repo = repo or ConnectRepository(session)
        self.ws_manager = ws_manager or get_connect_ws_manager()
        self.ai_service = ai_service or get_connect_ai_service()
        self.email_service = email_service or get_email_service()

    # -------------------------------------------------------------------------
    # Helper: Check Admin Authorization
    # -------------------------------------------------------------------------
    def _is_admin(self, user: User) -> bool:
        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        return user_role in ("super_admin", "hr_admin", "it_admin")

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
    ) -> dict[str, Any]:
        """List colleagues in tenant."""
        colleagues, total = await self.repo.get_colleagues(
            company_id=company_id,
            search=search,
            department=department,
            presence_filter=presence_filter,
            page=page,
            limit=limit,
            exclude_user_id=exclude_user_id,
        )
        return {
            "colleagues": colleagues,
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def unified_search(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Perform unified search."""
        if not query or not query.strip():
            return {"people": [], "channels": [], "messages": [], "files": []}
        return await self.repo.unified_search(
            company_id=company_id,
            user_id=user_id,
            query=query,
            limit=limit,
        )

    # =========================================================================
    # B. Direct Messaging
    # =========================================================================

    async def get_conversations(
        self,
        company_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Get user conversations with unread counts and presence."""
        convs = await self.repo.get_user_conversations(company_id, user_id)
        if not convs:
            return []

        all_user_ids = list({p.user_id for c in convs for p in c.participants if p.user_id})
        presences = await self.repo.get_batch_presence(all_user_ids, company_id) if all_user_ids else []
        presence_map = {pr.user_id: pr.status for pr in presences}

        results = []
        for c in convs:
            participant_items = []
            for p in c.participants:
                pres_status = presence_map.get(p.user_id, "offline")
                avatar = (
                    getattr(p.user, "profile_photo", None)
                    or getattr(p.user, "profile_photo_url", None)
                    if p.user else None
                )
                participant_items.append({
                    "id": p.id,
                    "user_id": p.user_id,
                    "name": p.user.name if p.user else "Unknown",
                    "email": p.user.email if p.user else "",
                    "avatar_url": avatar,
                    "role": getattr(p.user.role, "value", str(p.user.role)) if (p.user and p.user.role) else "employee",
                    "presence_status": pres_status,
                    "is_muted": p.is_muted,
                    "last_read_at": p.last_read_at,
                })

            results.append({
                "id": c.id,
                "company_id": c.company_id,
                "participants": participant_items,
                "last_message_preview": c.last_message_preview,
                "last_message_at": c.last_message_at,
                "unread_count": 0,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            })

        return results

    async def get_or_create_conversation(
        self,
        company_id: uuid.UUID,
        user: User,
        target_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Idempotently fetch or create DM conversation between user and target."""
        if user.id == target_user_id:
            raise AppException(message="Cannot start a conversation with yourself.", status_code=status.HTTP_400_BAD_REQUEST)

        conv, is_new = await self.repo.get_or_create_dm_conversation(company_id, user.id, target_user_id)
        if not conv:
            raise NotFoundException("Failed to retrieve or create conversation.")

        participant_uids = list({p.user_id for p in conv.participants if p.user_id})
        presences = await self.repo.get_batch_presence(participant_uids, company_id) if participant_uids else []
        presence_map = {pr.user_id: pr.status for pr in presences}

        participant_items = []
        for p in conv.participants:
            pres_status = presence_map.get(p.user_id, "offline")
            avatar = (
                getattr(p.user, "profile_photo", None)
                or getattr(p.user, "profile_photo_url", None)
                if p.user else None
            )
            participant_items.append({
                "id": p.id,
                "user_id": p.user_id,
                "name": p.user.name if p.user else "Unknown",
                "email": p.user.email if p.user else "",
                "avatar_url": avatar,
                "role": getattr(p.user.role, "value", str(p.user.role)) if (p.user and p.user.role) else "employee",
                "presence_status": pres_status,
                "is_muted": p.is_muted,
                "last_read_at": p.last_read_at,
            })

        return {
            "id": conv.id,
            "company_id": conv.company_id,
            "participants": participant_items,
            "last_message_preview": conv.last_message_preview,
            "last_message_at": conv.last_message_at,
            "unread_count": 0,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
        }

    async def get_conversation_messages(
        self,
        company_id: uuid.UUID,
        user: User,
        conversation_id: uuid.UUID,
        query: str | None = None,
        before_id: uuid.UUID | None = None,
        after_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get messages for conversation after verifying participant access."""
        is_participant = await self.repo.is_user_in_conversation(conversation_id, user.id, company_id)
        if not is_participant and not self._is_admin(user):
            raise ForbiddenException("You are not a participant in this conversation.")

        messages = await self.repo.get_conversation_messages(
            conversation_id=conversation_id,
            company_id=company_id,
            query=query,
            before_id=before_id,
            after_id=after_id,
            limit=limit,
        )

        return [self._format_message(m, user.id) for m in messages]

    async def send_conversation_message(
        self,
        company_id: uuid.UUID,
        user: User,
        conversation_id: uuid.UUID,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        voice_url: str | None = None,
        voice_duration: int | None = None,
        reply_to_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Send message in a direct conversation and broadcast real-time event."""
        is_participant = await self.repo.is_user_in_conversation(conversation_id, user.id, company_id)
        if not is_participant:
            raise ForbiddenException("You are not a participant in this conversation.")

        msg = await self.repo.create_message(
            company_id=company_id,
            sender_id=user.id,
            conversation_id=conversation_id,
            content=text,
            voice_url=voice_url,
            voice_duration=voice_duration,
            reply_to_id=reply_to_id,
            attachments=attachments,
        )

        formatted = self._format_message(msg, user.id)

        # Broadcast real-time event to conversation participants
        conv = await self.repo.get_conversation_by_id(conversation_id, company_id)
        if conv:
            for p in conv.participants:
                await self.ws_manager.send_to_user(
                    user_id=p.user_id,
                    company_id=company_id,
                    event="new_message",
                    data={"conversation_id": conversation_id, "message": formatted},
                )
                if p.user_id != user.id:
                    # Create notification
                    await self.repo.create_notification(
                        company_id=company_id,
                        recipient_id=p.user_id,
                        sender_id=user.id,
                        notification_type="message",
                        title=f"New message from {user.name}",
                        body=text[:100] if text else "Sent an attachment/audio message.",
                        resource_type="conversation",
                        resource_id=str(conversation_id),
                    )

        return formatted

    async def toggle_message_reaction(
        self,
        company_id: uuid.UUID,
        user: User,
        message_id: uuid.UUID,
        emoji: str,
    ) -> dict[str, Any]:
        """Toggle emoji reaction and broadcast event."""
        msg = await self.repo.get_message_by_id(message_id, company_id)
        if not msg:
            raise NotFoundException("Message not found.")

        reaction, is_added = await self.repo.toggle_message_reaction(message_id, user.id, company_id, emoji)
        reloaded = await self.repo.get_message_by_id(message_id, company_id)
        formatted = self._format_message(reloaded, user.id)

        # Broadcast reaction change
        if msg.conversation_id:
            conv = await self.repo.get_conversation_by_id(msg.conversation_id, company_id)
            if conv:
                for p in conv.participants:
                    await self.ws_manager.send_to_user(
                        p.user_id,
                        company_id,
                        "message_reaction",
                        {"message_id": message_id, "reactions": formatted["reactions"]},
                    )
        elif msg.channel_id:
            await self.ws_manager.send_to_room(
                f"channel:{msg.channel_id}",
                company_id,
                "message_reaction",
                {"message_id": message_id, "reactions": formatted["reactions"]},
            )

        return {"is_added": is_added, "reactions": formatted["reactions"]}

    async def toggle_message_pin(
        self,
        company_id: uuid.UUID,
        user: User,
        message_id: uuid.UUID,
        is_pinned: bool = True,
    ) -> dict[str, Any]:
        """Pin or unpin a message."""
        msg = await self.repo.get_message_by_id(message_id, company_id)
        if not msg:
            raise NotFoundException("Message not found.")

        updated = await self.repo.toggle_message_pin(message_id, user.id, company_id, is_pinned)
        return self._format_message(updated, user.id)

    async def delete_message(
        self,
        company_id: uuid.UUID,
        user: User,
        message_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Soft delete a message with RBAC authorization check."""
        msg = await self.repo.get_message_by_id(message_id, company_id)
        if not msg:
            raise NotFoundException("Message not found.")

        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        is_owner = msg.sender_id == user.id
        is_admin = user_role in ("hr_admin", "super_admin")

        if not is_owner and not is_admin:
            raise ForbiddenException("You are not authorized to delete this message.")

        await self.repo.soft_delete_message(message_id, company_id)

        # Broadcast deletion
        if msg.conversation_id:
            conv = await self.repo.get_conversation_by_id(msg.conversation_id, company_id)
            if conv:
                for p in conv.participants:
                    await self.ws_manager.send_to_user(
                        p.user_id,
                        company_id,
                        "message_deleted",
                        {"message_id": message_id, "conversation_id": msg.conversation_id},
                    )
        elif msg.channel_id:
            await self.ws_manager.send_to_room(
                f"channel:{msg.channel_id}",
                company_id,
                "message_deleted",
                {"message_id": message_id, "channel_id": msg.channel_id},
            )

        return {"deleted": True, "message_id": message_id}

    async def get_message_thread(
        self,
        company_id: uuid.UUID,
        user: User,
        parent_message_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Fetch all thread replies for a message."""
        parent = await self.repo.get_message_by_id(parent_message_id, company_id)
        if not parent:
            raise NotFoundException("Parent message not found.")

        replies = await self.repo.get_thread_messages(parent_message_id, company_id)
        return [self._format_message(r, user.id) for r in replies]

    async def post_thread_reply(
        self,
        company_id: uuid.UUID,
        user: User,
        parent_message_id: uuid.UUID,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        voice_url: str | None = None,
        voice_duration: int | None = None,
    ) -> dict[str, Any]:
        """Post a reply in a message thread."""
        parent = await self.repo.get_message_by_id(parent_message_id, company_id)
        if not parent:
            raise NotFoundException("Parent message not found.")

        reply = await self.repo.create_message(
            company_id=company_id,
            sender_id=user.id,
            conversation_id=parent.conversation_id,
            channel_id=parent.channel_id,
            parent_message_id=parent_message_id,
            content=text,
            voice_url=voice_url,
            voice_duration=voice_duration,
            attachments=attachments,
        )

        return self._format_message(reply, user.id)

    # =========================================================================
    # C. Team Channels
    # =========================================================================

    async def get_channels(
        self,
        company_id: uuid.UUID,
        user: User,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """List accessible channels."""
        channels = await self.repo.get_channels(company_id, user.id, query)
        results = []
        for ch in channels:
            is_member = any(m.user_id == user.id for m in ch.members)
            results.append({
                "id": ch.id,
                "name": ch.name,
                "description": ch.description,
                "is_private": ch.is_private,
                "is_archived": ch.is_archived,
                "created_by": ch.created_by,
                "members_count": len(ch.members),
                "unread_count": 0,
                "is_member": is_member,
                "created_at": ch.created_at,
                "updated_at": ch.updated_at,
            })
        return results

    async def create_channel(
        self,
        company_id: uuid.UUID,
        user: User,
        name: str,
        description: str | None = None,
        is_private: bool = False,
        member_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """Create new channel."""
        ch = await self.repo.create_channel(
            company_id=company_id,
            creator_id=user.id,
            name=name,
            description=description,
            is_private=is_private,
            member_ids=member_ids,
        )
        return self._format_channel_detail(ch, user.id)

    async def get_channel_detail(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Get channel details with permissions and member list."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        is_member = any(m.user_id == user.id for m in ch.members)
        if ch.is_private and not is_member and not self._is_admin(user):
            raise ForbiddenException("You do not have permission to access this private channel.")

        return self._format_channel_detail(ch, user.id)

    async def get_channel_messages(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
        query: str | None = None,
        pinned_only: bool = False,
        before_id: uuid.UUID | None = None,
        after_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get messages in a channel."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        is_member = any(m.user_id == user.id for m in ch.members)
        if ch.is_private and not is_member and not self._is_admin(user):
            raise ForbiddenException("You do not have access to messages in this private channel.")

        messages = await self.repo.get_channel_messages(
            channel_id=channel_id,
            company_id=company_id,
            query=query,
            pinned_only=pinned_only,
            before_id=before_id,
            after_id=after_id,
            limit=limit,
        )
        return [self._format_message(m, user.id) for m in messages]

    async def send_channel_message(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        voice_url: str | None = None,
        voice_duration: int | None = None,
        reply_to_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Post message to a channel."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        is_member = any(m.user_id == user.id for m in ch.members)
        if ch.is_private and not is_member and not self._is_admin(user):
            raise ForbiddenException("You are not a member of this private channel.")

        msg = await self.repo.create_message(
            company_id=company_id,
            sender_id=user.id,
            channel_id=channel_id,
            content=text,
            voice_url=voice_url,
            voice_duration=voice_duration,
            reply_to_id=reply_to_id,
            attachments=attachments,
        )

        formatted = self._format_message(msg, user.id)

        # Broadcast to channel room
        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "new_message",
            {"channel_id": channel_id, "message": formatted},
        )

        return formatted

    async def update_channel(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        is_private: bool | None = None,
        is_archived: bool | None = None,
    ) -> dict[str, Any]:
        """Update channel details with RBAC authorization check."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        is_creator = ch.created_by == user.id
        is_host = any(m.user_id == user.id and m.role in ("host", "admin") for m in ch.members)
        is_admin = user_role in ("hr_admin", "super_admin", "it_admin")

        if not is_creator and not is_host and not is_admin:
            raise ForbiddenException("Only the channel creator, host, or an administrator can update this channel.")

        updated = await self.repo.update_channel(
            channel_id=channel_id,
            company_id=company_id,
            name=name,
            description=description,
            is_private=is_private,
            is_archived=is_archived,
        )
        formatted = self._format_channel_detail(updated, user.id)

        # Broadcast channel update event
        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "channel_updated",
            {"channel_id": channel_id, "channel": formatted},
        )

        return formatted

    async def delete_channel(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Soft delete a channel with RBAC authorization check."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        is_creator = ch.created_by == user.id
        is_host = any(m.user_id == user.id and m.role in ("host", "admin") for m in ch.members)
        is_admin = user_role in ("hr_admin", "super_admin", "it_admin")

        if not is_creator and not is_host and not is_admin:
            raise ForbiddenException("Only the channel creator, host, or an administrator can delete this channel.")

        await self.repo.soft_delete_channel(channel_id, company_id)

        # Broadcast channel deleted event
        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "channel_deleted",
            {"channel_id": channel_id},
        )

        return {"deleted": True, "channel_id": channel_id}

    async def add_channel_members(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
        member_ids: list[uuid.UUID],
    ) -> dict[str, Any]:
        """Add members to channel with authorization check."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        is_member = any(m.user_id == user.id for m in ch.members)
        is_admin = self._is_admin(user)

        if ch.is_private and not is_member and not is_admin:
            raise ForbiddenException("You do not have permission to add members to this private channel.")

        updated = await self.repo.add_channel_members(channel_id, company_id, member_ids)
        formatted = self._format_channel_detail(updated, user.id)

        # Broadcast member addition
        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "channel_members_added",
            {"channel_id": channel_id, "member_ids": member_ids, "members": formatted["members"]},
        )

        return formatted

    async def remove_channel_member(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Remove a member from a channel with authorization check."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        is_self = user.id == target_user_id
        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        is_creator = ch.created_by == user.id
        is_host = any(m.user_id == user.id and m.role in ("host", "admin") for m in ch.members)
        is_admin = user_role in ("hr_admin", "super_admin", "it_admin")

        if not is_self and not is_creator and not is_host and not is_admin:
            raise ForbiddenException("You do not have permission to remove this member from the channel.")

        await self.repo.remove_channel_member(channel_id, target_user_id, company_id)

        # Broadcast member removal
        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "channel_member_removed",
            {"channel_id": channel_id, "user_id": target_user_id},
        )

        return {"removed": True, "channel_id": channel_id, "user_id": target_user_id}

    async def leave_channel(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Leave a channel."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        await self.repo.remove_channel_member(channel_id, user.id, company_id)

        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "channel_member_removed",
            {"channel_id": channel_id, "user_id": user.id},
        )

        return {"left": True, "channel_id": channel_id}

    async def archive_channel(
        self,
        company_id: uuid.UUID,
        user: User,
        channel_id: uuid.UUID,
        is_archived: bool = True,
    ) -> dict[str, Any]:
        """Archive channel with authorization check."""
        ch = await self.repo.get_channel_by_id(channel_id, company_id)
        if not ch:
            raise NotFoundException("Channel not found.")

        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        is_creator = ch.created_by == user.id
        is_host = any(m.user_id == user.id and m.role in ("host", "admin") for m in ch.members)
        is_admin = user_role in ("hr_admin", "super_admin", "it_admin")

        if not is_creator and not is_host and not is_admin:
            raise ForbiddenException("Only the channel creator, host, or an administrator can archive this channel.")

        updated = await self.repo.archive_channel(channel_id, company_id, is_archived)
        formatted = self._format_channel_detail(updated, user.id)

        # Broadcast channel archive status
        await self.ws_manager.send_to_room(
            f"channel:{channel_id}",
            company_id,
            "channel_archived",
            {"channel_id": channel_id, "is_archived": is_archived},
        )

        return formatted

    # =========================================================================
    # D. Calls & WebRTC
    # =========================================================================

    def get_ice_servers(self) -> dict[str, Any]:
        """Return WebRTC STUN/TURN server configuration."""
        return {
            "iceServers": [
                {"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"]}
            ]
        }

    async def get_call_history(
        self,
        company_id: uuid.UUID,
        user: User,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get call logs for user with full frontend and backward compatibility."""
        logs = await self.repo.get_call_history(company_id, user.id, limit)
        results = []
        for c in logs:
            caller_name = c.caller.name if c.caller else "Colleague"
            caller_email = c.caller.email if c.caller else ""
            caller_avatar = getattr(c.caller, "profile_photo", None) if c.caller else None
            caller_dict = {
                "id": c.caller_id,
                "name": caller_name,
                "email": caller_email,
                "avatar": caller_avatar,
                "profile_photo": caller_avatar,
            }

            callee_name = c.callee.name if c.callee else "Colleague"
            callee_email = c.callee.email if c.callee else ""
            callee_avatar = getattr(c.callee, "profile_photo", None) if c.callee else None
            callee_dict = {
                "id": c.callee_id,
                "name": callee_name,
                "email": callee_email,
                "avatar": callee_avatar,
                "profile_photo": callee_avatar,
            }

            is_incoming = (c.callee_id == user.id)
            direction = "incoming" if is_incoming else "outgoing"

            results.append({
                "id": c.id,
                "callId": c.id,
                "call_id": c.id,
                "caller_id": c.caller_id,
                "caller_name": caller_name,
                "caller_avatar": caller_avatar,
                "caller": caller_dict,
                "callee_id": c.callee_id,
                "callee_name": callee_name,
                "callee_avatar": callee_avatar,
                "callee": callee_dict,
                "call_type": c.call_type,
                "callType": c.call_type,
                "type": c.call_type,
                "status": c.status,
                "room_id": c.room_id,
                "roomId": c.room_id,
                "duration_seconds": c.duration_seconds,
                "duration": c.duration_seconds,
                "started_at": c.started_at,
                "startedAt": c.started_at.isoformat() if c.started_at else None,
                "connected_at": c.connected_at,
                "connectedAt": c.connected_at.isoformat() if c.connected_at else None,
                "ended_at": c.ended_at,
                "endedAt": c.ended_at.isoformat() if c.ended_at else None,
                "created_at": c.created_at,
                "direction": direction,
            })
        return results

    async def get_call_detail(
        self,
        company_id: uuid.UUID,
        user: User,
        call_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Fetch single call log details with tenant and participant authorization verification."""
        call = await self.repo.get_call_by_id(call_id, company_id)
        if not call:
            raise NotFoundException("Call session not found.")

        if user.id != call.caller_id and user.id != call.callee_id and not self._is_admin(user):
            raise ForbiddenException("You are not authorized to view this call.")

        caller_name = call.caller.name if call.caller else "Colleague"
        caller_avatar = getattr(call.caller, "profile_photo", None) if call.caller else None
        callee_name = call.callee.name if call.callee else "Colleague"
        callee_avatar = getattr(call.callee, "profile_photo", None) if call.callee else None

        is_incoming = (call.callee_id == user.id)
        return {
            "id": call.id,
            "callId": call.id,
            "call_id": call.id,
            "caller_id": call.caller_id,
            "caller_name": caller_name,
            "caller_avatar": caller_avatar,
            "caller": {
                "id": call.caller_id,
                "name": caller_name,
                "email": call.caller.email if call.caller else "",
                "avatar": caller_avatar,
                "profile_photo": caller_avatar,
            },
            "callee_id": call.callee_id,
            "callee_name": callee_name,
            "callee_avatar": callee_avatar,
            "callee": {
                "id": call.callee_id,
                "name": callee_name,
                "email": call.callee.email if call.callee else "",
                "avatar": callee_avatar,
                "profile_photo": callee_avatar,
            },
            "call_type": call.call_type,
            "callType": call.call_type,
            "type": call.call_type,
            "status": call.status,
            "room_id": call.room_id,
            "roomId": call.room_id,
            "duration_seconds": call.duration_seconds,
            "duration": call.duration_seconds,
            "started_at": call.started_at,
            "startedAt": call.started_at.isoformat() if call.started_at else None,
            "connected_at": call.connected_at,
            "connectedAt": call.connected_at.isoformat() if call.connected_at else None,
            "ended_at": call.ended_at,
            "endedAt": call.ended_at.isoformat() if call.ended_at else None,
            "created_at": call.created_at,
            "direction": "incoming" if is_incoming else "outgoing",
        }

    async def initiate_call(
        self,
        company_id: uuid.UUID,
        user: User,
        target_user_id: uuid.UUID,
        call_type: str = "audio",
    ) -> dict[str, Any]:
        """Initiate call and send real-time call:incoming and incoming_call events to target user."""
        if user.id == target_user_id:
            raise AppException(message="Cannot call yourself.", status_code=status.HTTP_400_BAD_REQUEST)

        # 1. Validate target user exists, is active, and belongs to caller's company
        target_user = await self.repo.get_active_user_in_company(target_user_id, company_id)
        if not target_user:
            raise ForbiddenException("Recipient colleague not found or does not belong to your company.")

        is_callee_online = self.ws_manager.is_online(target_user_id)
        room_id = f"call_{uuid.uuid4().hex[:12]}"

        call = await self.repo.create_call_log(
            company_id=company_id,
            caller_id=user.id,
            callee_id=target_user_id,
            call_type=call_type,
            room_id=room_id,
            status="ringing",
        )

        caller_avatar = getattr(user, "profile_photo", None)
        caller_dict = {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "avatar": caller_avatar,
            "profile_photo": caller_avatar,
        }
        callee_avatar = getattr(target_user, "profile_photo", None)
        callee_dict = {
            "id": str(target_user_id),
            "name": target_user.name,
            "email": target_user.email,
            "avatar": callee_avatar,
            "profile_photo": callee_avatar,
        }

        call_data = {
            "id": str(call.id),
            "callId": str(call.id),
            "call_id": str(call.id),
            "caller_id": str(user.id),
            "callerId": str(user.id),
            "caller_name": user.name,
            "caller_avatar": caller_avatar,
            "caller": caller_dict,
            "receiver_id": str(target_user_id),
            "receiverId": str(target_user_id),
            "callee_id": str(target_user_id),
            "calleeId": str(target_user_id),
            "target_user_id": str(target_user_id),
            "targetUserId": str(target_user_id),
            "callee_name": target_user.name,
            "callee_avatar": callee_avatar,
            "callee": callee_dict,
            "call_type": call_type,
            "callType": call_type,
            "type": call_type,
            "status": "ringing",
            "room_id": room_id,
            "roomId": room_id,
            "started_at": call.started_at,
            "startedAt": call.started_at.isoformat() if call.started_at else None,
            "is_receiver_online": is_callee_online,
        }

        logger.info(
            "CALL_STARTED | call_id=%s caller_id=%s receiver_id=%s call_type=%s receiver_online=%s",
            call.id, user.id, target_user_id, call_type, is_callee_online,
        )

        # Send dual real-time call invitation to target:
        # 1. call:incoming (frontend canonical expectation)
        delivered_1 = await self.ws_manager.send_to_user(
            target_user_id,
            company_id,
            "call:incoming",
            call_data,
        )
        # 2. incoming_call (legacy / backend alternative expectation)
        await self.ws_manager.send_to_user(
            target_user_id,
            company_id,
            "incoming_call",
            call_data,
        )

        is_delivered = (delivered_1 > 0) if isinstance(delivered_1, int) else bool(delivered_1)
        if is_delivered:
            logger.info(
                "CALL_INCOMING_DELIVERED | call_id=%s receiver_id=%s",
                call.id, target_user_id,
            )
        else:
            logger.warning(
                "CALL_INCOMING_DELIVERY_FAILED | call_id=%s receiver_id=%s reason=no_active_sockets",
                call.id, target_user_id,
            )

        # Create persistent notification record for callee
        try:
            await self.repo.create_notification(
                company_id=company_id,
                recipient_id=target_user_id,
                sender_id=user.id,
                notification_type="call",
                title=f"Incoming {call_type.capitalize()} Call",
                body=f"{user.name} is calling you ({call_type.capitalize()}).",
                resource_type="call",
                resource_id=str(call.id),
            )
        except Exception as e:
            logger.warning("Failed to create call notification: %s", e)

        return call_data

    async def update_call_status(
        self,
        company_id: uuid.UUID,
        user: User,
        call_id: uuid.UUID,
        new_status: str,
    ) -> dict[str, Any]:
        """Update call state and notify participants via dual-compatible WebSocket events."""
        call = await self.repo.get_call_by_id(call_id, company_id)
        if not call:
            raise NotFoundException("Call session not found.")

        if user.id != call.caller_id and user.id != call.callee_id and not self._is_admin(user):
            raise ForbiddenException("You are not a participant in this call.")

        # Normalize incoming status
        target_status = new_status.lower().strip()
        if target_status == "accepted":
            target_status = "connected"
        elif target_status == "declined":
            target_status = "rejected"
        elif target_status == "canceled":
            target_status = "cancelled"

        current_status = (call.status or "").lower().strip()
        terminal_states = {"ended", "rejected", "cancelled", "missed", "failed"}

        # State transition validation
        if current_status in terminal_states:
            if target_status in ("connected", "accepted", "ringing", "initiated"):
                raise AppException(
                    message=f"Cannot transition call from '{current_status}' to '{target_status}'. Call is already closed.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            # If already in terminal state and receiving redundant end/cancel, return cleanly (idempotent)
            return {
                "id": str(call.id),
                "callId": str(call.id),
                "call_id": str(call.id),
                "status": current_status,
                "duration_seconds": call.duration_seconds,
                "duration": call.duration_seconds,
                "connected_at": call.connected_at,
                "connectedAt": call.connected_at.isoformat() if call.connected_at else None,
                "ended_at": call.ended_at,
                "endedAt": call.ended_at.isoformat() if call.ended_at else None,
            }

        updated = await self.repo.update_call_status(call_id, company_id, target_status)

        # Identify caller and callee
        other_user_id = call.callee_id if user.id == call.caller_id else call.caller_id

        status_payload = {
            "call_id": str(call_id),
            "callId": str(call_id),
            "id": str(call_id),
            "caller_id": str(call.caller_id),
            "receiver_id": str(call.callee_id),
            "callee_id": str(call.callee_id),
            "status": target_status,
            "duration_seconds": updated.duration_seconds,
            "duration": updated.duration_seconds,
            "connected_at": updated.connected_at.isoformat() if updated.connected_at else None,
            "ended_at": updated.ended_at.isoformat() if updated.ended_at else None,
        }

        # Dispatch specific frontend lifecycle event
        if target_status == "connected":
            logger.info("CALL_ACCEPTED | call_id=%s caller_id=%s callee_id=%s", call_id, call.caller_id, call.callee_id)
            await self.ws_manager.send_to_user(
                call.caller_id,
                company_id,
                "call:accepted",
                status_payload,
            )
            await self.ws_manager.send_to_user(
                call.callee_id,
                company_id,
                "call:accepted",
                status_payload,
            )
        elif target_status == "rejected":
            logger.info("CALL_REJECTED | call_id=%s caller_id=%s callee_id=%s", call_id, call.caller_id, call.callee_id)
            await self.ws_manager.send_to_user(
                call.caller_id,
                company_id,
                "call:rejected",
                status_payload,
            )
        elif target_status == "cancelled":
            logger.info("CALL_CANCELLED | call_id=%s caller_id=%s callee_id=%s", call_id, call.caller_id, call.callee_id)
            await self.ws_manager.send_to_user(
                call.callee_id,
                company_id,
                "call:cancelled",
                status_payload,
            )
        elif target_status in ("ended", "missed", "failed"):
            logger.info("CALL_ENDED | call_id=%s caller_id=%s callee_id=%s status=%s duration=%d", call_id, call.caller_id, call.callee_id, target_status, updated.duration_seconds)
            # Notify both participants that call ended
            await self.ws_manager.send_to_user(
                call.caller_id,
                company_id,
                "call:ended",
                status_payload,
            )
            await self.ws_manager.send_to_user(
                call.callee_id,
                company_id,
                "call:ended",
                status_payload,
            )

        # Also emit standard legacy call_status_changed event to both
        await self.ws_manager.send_to_user(
            call.caller_id,
            company_id,
            "call_status_changed",
            status_payload,
        )
        await self.ws_manager.send_to_user(
            call.callee_id,
            company_id,
            "call_status_changed",
            status_payload,
        )

        # Create missed call notification if callee missed it
        if target_status == "missed":
            try:
                await self.repo.create_notification(
                    company_id=company_id,
                    recipient_id=call.callee_id,
                    sender_id=call.caller_id,
                    notification_type="call",
                    title=f"Missed {call.call_type.capitalize()} Call",
                    body=f"You missed a {call.call_type} call from {user.name}.",
                    resource_type="call",
                    resource_id=str(call.id),
                )
            except Exception as e:
                logger.warning("Failed to create missed call notification: %s", e)

        return {
            "id": str(updated.id),
            "callId": str(updated.id),
            "call_id": str(updated.id),
            "status": updated.status,
            "duration_seconds": updated.duration_seconds,
            "duration": updated.duration_seconds,
            "connected_at": updated.connected_at,
            "connectedAt": updated.connected_at.isoformat() if updated.connected_at else None,
            "ended_at": updated.ended_at,
            "endedAt": updated.ended_at.isoformat() if updated.ended_at else None,
        }

    async def handle_call_signal(
        self,
        company_id: uuid.UUID,
        user: User,
        call_id: uuid.UUID,
        signal_type: str,
        payload: dict[str, Any],
        target_user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Relay WebRTC signaling message (SDP offer/answer, ICE candidates) without media."""
        call = await self.repo.get_call_by_id(call_id, company_id)
        if not call:
            raise NotFoundException("Call session not found.")

        if user.id != call.caller_id and user.id != call.callee_id:
            raise ForbiddenException("You are not part of this call session.")

        terminal_states = {"ended", "rejected", "cancelled", "missed", "failed"}
        if (call.status or "").lower() in terminal_states:
            raise AppException(message="Cannot relay signals for an ended or closed call.", status_code=status.HTTP_400_BAD_REQUEST)

        recipient_id = target_user_id or (call.callee_id if user.id == call.caller_id else call.caller_id)
        if recipient_id not in (call.caller_id, call.callee_id):
            raise ForbiddenException("Signal target is not a participant in this call.")

        signal_data = {
            "call_id": str(call_id),
            "callId": str(call_id),
            "id": str(call_id),
            "from_user_id": str(user.id),
            "fromUserId": str(user.id),
            "target_user_id": str(recipient_id),
            "targetUserId": str(recipient_id),
            "receiver_id": str(recipient_id),
            "receiverId": str(recipient_id),
            "type": signal_type,
            "payload": payload,
            "signal": payload,
        }

        # If payload contains sdp/candidate, expose at top level too
        if isinstance(payload, dict):
            if "sdp" in payload:
                signal_data["sdp"] = payload["sdp"]
            if "candidate" in payload:
                signal_data["candidate"] = payload["candidate"]

        logger.debug(
            "WEBRTC_SIGNAL_FORWARDED | call_id=%s from_user=%s to_user=%s signal_type=%s",
            call_id, user.id, recipient_id, signal_type,
        )

        # Dual WebSocket event emission: webrtc:signal (frontend canonical) & call_signal (backend alternative)
        await self.ws_manager.send_to_user(
            recipient_id,
            company_id,
            "webrtc:signal",
            signal_data,
        )
        await self.ws_manager.send_to_user(
            recipient_id,
            company_id,
            "call_signal",
            signal_data,
        )

        return {"relayed": True, "type": signal_type, "recipient_id": str(recipient_id)}

    # =========================================================================
    # E. Video Meetings
    # =========================================================================

    async def get_meetings(
        self,
        company_id: uuid.UUID,
        user: User,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get meetings list."""
        meetings = await self.repo.get_user_meetings(company_id, user.id, status_filter)
        return [self._format_meeting_detail(m) for m in meetings]

    async def create_meeting(
        self,
        company_id: uuid.UUID,
        user: User,
        title: str,
        description: str | None = None,
        meeting_type: str = "instant",
        start_time: Any = None,
        duration_minutes: int = 30,
        participant_ids: list[uuid.UUID] | None = None,
        allow_screen_share: bool = True,
        allow_microphone: bool = True,
        allow_camera: bool = True,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """Create meeting."""
        meeting_code = f"meet-{secrets.token_hex(4)}"
        meeting = await self.repo.create_meeting(
            company_id=company_id,
            host_id=user.id,
            title=title,
            meeting_code=meeting_code,
            description=description,
            meeting_type=meeting_type,
            start_time=start_time,
            duration_minutes=duration_minutes,
            participant_ids=participant_ids,
            allow_screen_share=allow_screen_share,
            allow_microphone=allow_microphone,
            allow_camera=allow_camera,
            is_private=is_private,
        )

        # Notify participants
        if participant_ids:
            for pid in participant_ids:
                if pid != user.id:
                    await self.repo.create_notification(
                        company_id=company_id,
                        recipient_id=pid,
                        sender_id=user.id,
                        notification_type="meeting",
                        title=f"Invitation to meeting: {title}",
                        body=f"Meeting code: {meeting_code}",
                        resource_type="meeting",
                        resource_id=str(meeting.id),
                    )

        return self._format_meeting_detail(meeting)

    async def get_meeting_detail(
        self,
        company_id: uuid.UUID,
        user: User,
        meeting_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Fetch meeting details."""
        meeting = await self.repo.get_meeting_by_id(meeting_id, company_id)
        if not meeting:
            raise NotFoundException("Meeting not found.")

        is_participant = any(p.user_id == user.id for p in meeting.participants)
        if meeting.is_private and not is_participant and meeting.host_id != user.id and not self._is_admin(user):
            raise ForbiddenException("You are not invited to this private meeting.")

        return self._format_meeting_detail(meeting)

    async def join_meeting(
        self,
        company_id: uuid.UUID,
        user: User,
        meeting_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Join meeting and notify participants."""
        meeting = await self.repo.get_meeting_by_id(meeting_id, company_id)
        if not meeting:
            raise NotFoundException("Meeting not found.")

        if meeting.status == "ended":
            raise AppException(message="This meeting has already ended.", status_code=status.HTTP_400_BAD_REQUEST)

        participant = await self.repo.join_meeting(meeting_id, user.id, company_id)

        # Broadcast participant joined
        await self.ws_manager.send_to_room(
            f"meeting:{meeting_id}",
            company_id,
            "meeting_participant_joined",
            {
                "meeting_id": meeting_id,
                "user_id": user.id,
                "name": user.name,
                "avatar": getattr(user, "profile_photo", None),
                "role": participant.role,
            },
        )

        return self._format_meeting_detail(meeting)

    async def leave_meeting(
        self,
        company_id: uuid.UUID,
        user: User,
        meeting_id: uuid.UUID,
        end_for_everyone: bool = False,
    ) -> dict[str, Any]:
        """Leave or end meeting."""
        meeting = await self.repo.get_meeting_by_id(meeting_id, company_id)
        if not meeting:
            raise NotFoundException("Meeting not found.")

        is_host = meeting.host_id == user.id
        if end_for_everyone and not is_host and not self._is_admin(user):
            raise ForbiddenException("Only the meeting host can end the meeting for everyone.")

        updated = await self.repo.leave_meeting(
            meeting_id=meeting_id,
            user_id=user.id,
            company_id=company_id,
            end_for_everyone=end_for_everyone,
        )

        # Broadcast leave or end event
        if end_for_everyone:
            await self.ws_manager.send_to_room(
                f"meeting:{meeting_id}",
                company_id,
                "meeting_ended",
                {"meeting_id": meeting_id},
            )
        else:
            await self.ws_manager.send_to_room(
                f"meeting:{meeting_id}",
                company_id,
                "meeting_participant_left",
                {"meeting_id": meeting_id, "user_id": user.id},
            )

        return {"left": True, "meeting_id": meeting_id, "status": updated.status}

    async def send_meeting_message(
        self,
        company_id: uuid.UUID,
        user: User,
        meeting_id: uuid.UUID,
        content: str,
    ) -> dict[str, Any]:
        """Post chat message inside a meeting."""
        meeting = await self.repo.get_meeting_by_id(meeting_id, company_id)
        if not meeting:
            raise NotFoundException("Meeting not found.")

        msg = await self.repo.add_meeting_message(meeting_id, user.id, company_id, content)

        data = {
            "id": msg.id,
            "meeting_id": meeting_id,
            "sender_id": user.id,
            "sender_name": user.name,
            "sender_avatar": getattr(user, "profile_photo", None),
            "content": content,
            "created_at": msg.created_at,
        }

        # Broadcast to meeting room
        await self.ws_manager.send_to_room(
            f"meeting:{meeting_id}",
            company_id,
            "meeting_chat_message",
            data,
        )

        return data

    # =========================================================================
    # F. Shared Files
    # =========================================================================

    async def get_shared_files(
        self,
        company_id: uuid.UUID,
        user: User,
        filter_type: str = "all",
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Fetch shared files."""
        files, total = await self.repo.get_shared_files(
            company_id=company_id,
            user_id=user.id,
            filter_type=filter_type,
            search=search,
            page=page,
            limit=limit,
        )

        items = [
            {
                "id": f.id,
                "file_name": f.file_name,
                "file_url": f.file_url,
                "file_type": f.file_type,
                "file_category": f.file_category,
                "file_size": f.file_size,
                "uploader_id": f.uploader_id,
                "uploader_name": f.uploader.name if f.uploader else "Unknown",
                "created_at": f.created_at,
            }
            for f in files
        ]

        return {
            "files": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    async def upload_shared_file(
        self,
        company_id: uuid.UUID,
        user: User,
        file: UploadFile,
    ) -> dict[str, Any]:
        """Upload and store a file directly."""
        file_bytes = await file.read()
        if not file_bytes or len(file_bytes) == 0:
            raise AppException(message="Uploaded file is empty.", status_code=status.HTTP_400_BAD_REQUEST)

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise AppException(message="File size exceeds maximum limit of 50MB.", status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        original_filename = file.filename or "file.pdf"
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(message=f"Unsupported file format '{ext}'.", status_code=status.HTTP_400_BAD_REQUEST)

        # Categorize
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            category = "images"
        elif ext in (".mp4", ".mov", ".avi"):
            category = "videos"
        elif ext in (".xls", ".xlsx", ".csv"):
            category = "spreadsheets"
        else:
            category = "documents"

        upload_dir = os.path.join(settings.UPLOAD_DIR, "connect")
        os.makedirs(upload_dir, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex}_{os.path.basename(original_filename)}"
        file_path = os.path.join(upload_dir, unique_name)

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        file_url = f"/uploads/connect/{unique_name}"
        content_type = file.content_type or "application/octet-stream"

        record = await self.repo.create_shared_file(
            company_id=company_id,
            uploader_id=user.id,
            file_name=original_filename,
            file_url=file_url,
            file_path=os.path.abspath(file_path),
            file_type=content_type,
            file_category=category,
            file_size=len(file_bytes),
        )

        return {
            "id": record.id,
            "file_name": record.file_name,
            "file_url": record.file_url,
            "file_type": record.file_type,
            "file_category": record.file_category,
            "file_size": record.file_size,
            "uploader_id": user.id,
            "uploader_name": user.name,
            "created_at": record.created_at,
        }

    async def delete_shared_file(
        self,
        company_id: uuid.UUID,
        user: User,
        file_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Delete shared file with RBAC authorization check."""
        record = await self.repo.get_shared_file_by_id(file_id, company_id)
        if not record:
            raise NotFoundException("File not found.")

        user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
        is_owner = record.uploader_id == user.id
        is_admin = user_role in ("hr_admin", "super_admin", "it_admin")

        if not is_owner and not is_admin:
            raise ForbiddenException("You are not authorized to delete this file.")

        await self.repo.delete_shared_file(file_id, company_id)

        # Cleanup disk if exists
        try:
            if os.path.exists(record.file_path):
                os.remove(record.file_path)
        except Exception as e:
            logger.warning("Could not delete file from disk: %s", e)

        return {"deleted": True, "file_id": file_id}

    # =========================================================================
    # G. Presence
    # =========================================================================

    async def update_presence(
        self,
        company_id: uuid.UUID,
        user: User,
        pres_status: str,
        custom_status: str | None = None,
    ) -> dict[str, Any]:
        """Update presence and broadcast presence_changed event."""
        pres = await self.repo.upsert_presence(
            user_id=user.id,
            company_id=company_id,
            status=pres_status,
            custom_status=custom_status,
        )

        data = {
            "user_id": user.id,
            "status": pres.status,
            "custom_status": pres.custom_status,
            "last_seen_at": pres.last_seen_at,
            "updated_at": pres.updated_at,
        }

        # Broadcast to all connected tenant users
        await self.ws_manager.broadcast_to_tenant(
            company_id=company_id,
            event="presence_changed",
            data=data,
            exclude_user_id=user.id,
        )

        return data

    async def get_batch_presence(
        self,
        company_id: uuid.UUID,
        user_ids: list[uuid.UUID],
    ) -> list[dict[str, Any]]:
        """Get presence records for multiple users."""
        records = await self.repo.get_batch_presence(user_ids, company_id)
        found_map = {r.user_id: r for r in records}
        results = []
        for uid in user_ids:
            if uid in found_map:
                r = found_map[uid]
                results.append({
                    "user_id": r.user_id,
                    "status": r.status,
                    "custom_status": r.custom_status,
                    "last_seen_at": r.last_seen_at,
                    "updated_at": r.updated_at,
                })
            else:
                results.append({
                    "user_id": uid,
                    "status": "offline",
                    "custom_status": None,
                    "last_seen_at": None,
                    "updated_at": None,
                })
        return results

    # =========================================================================
    # H. Notifications
    # =========================================================================

    async def get_notifications(
        self,
        company_id: uuid.UUID,
        user: User,
        unread_only: bool = False,
        limit: int = 50,
        notification_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch notifications."""
        notifs = await self.repo.get_notifications(
            recipient_id=user.id,
            company_id=company_id,
            unread_only=unread_only,
            limit=limit,
            notification_type=notification_type,
        )
        return [
            {
                "id": n.id,
                "notification_type": n.notification_type,
                "title": n.title,
                "body": n.body,
                "resource_type": n.resource_type,
                "resource_id": n.resource_id,
                "is_read": n.is_read,
                "read_at": n.read_at,
                "sender_id": n.sender_id,
                "sender_name": n.sender.name if n.sender else None,
                "created_at": n.created_at,
            }
            for n in notifs
        ]

    async def mark_notification_read(
        self,
        company_id: uuid.UUID,
        user: User,
        notification_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Mark notification read."""
        notif = await self.repo.mark_notification_read(notification_id, user.id, company_id)
        if not notif:
            raise NotFoundException("Notification not found.")
        return {"id": notif.id, "is_read": notif.is_read, "read_at": notif.read_at}

    async def delete_notifications(
        self,
        company_id: uuid.UUID,
        user: User,
    ) -> dict[str, Any]:
        """Clear all notifications for user."""
        await self.repo.delete_user_notifications(user.id, company_id)
        return {"cleared": True}

    # =========================================================================
    # I. Sound Settings
    # =========================================================================

    async def get_sound_settings(
        self,
        company_id: uuid.UUID,
        user: User,
    ) -> dict[str, Any]:
        """Get user sound settings with fallback defaults."""
        s = await self.repo.get_sound_settings(user.id, company_id)
        if not s:
            return {
                "masterVolume": 80,
                "isMuted": False,
                "incomingCallChime": True,
                "outgoingCallChime": True,
                "messageChime": True,
                "mentionChime": True,
                "meetingChime": True,
                "ringtone": "aurix_default_ringtone.mp3",
                "notificationTone": "aurix_default_notification.mp3",
            }
        return {
            "masterVolume": s.master_volume,
            "isMuted": s.is_muted,
            "incomingCallChime": s.incoming_call_chime,
            "outgoingCallChime": s.outgoing_call_chime,
            "messageChime": s.message_chime,
            "mentionChime": s.mention_chime,
            "meetingChime": s.meeting_chime,
            "ringtone": s.ringtone,
            "notificationTone": s.notification_tone,
        }

    async def update_sound_settings(
        self,
        company_id: uuid.UUID,
        user: User,
        master_volume: int = 80,
        is_muted: bool = False,
        incoming_call_chime: bool = True,
        outgoing_call_chime: bool = True,
        message_chime: bool = True,
        mention_chime: bool = True,
        meeting_chime: bool = True,
        ringtone: str = "aurix_default_ringtone.mp3",
        notification_tone: str = "aurix_default_notification.mp3",
    ) -> dict[str, Any]:
        """Persist user sound settings."""
        s = await self.repo.upsert_sound_settings(
            user_id=user.id,
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
        return {
            "masterVolume": s.master_volume,
            "isMuted": s.is_muted,
            "incomingCallChime": s.incoming_call_chime,
            "outgoingCallChime": s.outgoing_call_chime,
            "messageChime": s.message_chime,
            "mentionChime": s.mention_chime,
            "meetingChime": s.meeting_chime,
            "ringtone": s.ringtone,
            "notificationTone": s.notification_tone,
        }

    # =========================================================================
    # J. AI Communication Copilot
    # =========================================================================

    async def transform_ai(
        self,
        text: str,
        action: str,
        tone: str | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Transform text using AI copilot."""
        transformed = await self.ai_service.transform_text(
            text=text,
            action=action,
            tone=tone,
            context=context,
        )
        return {
            "original_text": text,
            "transformed_text": transformed,
            "action": action,
            "tone": tone,
        }

    # =========================================================================
    # K. Mail Dispatch
    # =========================================================================

    async def dispatch_mail(
        self,
        company_id: uuid.UUID,
        user: User,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Dispatch email reusing existing OFC360 email service."""
        from app.services.email_service import send_email

        all_recipients = list(set(to + (cc or []) + (bcc or [])))
        if not all_recipients:
            raise AppException(message="At least one recipient is required.", status_code=status.HTTP_400_BAD_REQUEST)

        html_body = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <p><strong>Sent by:</strong> {user.name} ({user.email})</p>
            <hr style="border: 0; border-top: 1px solid #eee; margin: 15px 0;">
            {body}
        </div>
        """

        for recipient in all_recipients:
            try:
                await send_email(recipient, subject, html_body)
            except Exception as e:
                logger.warning("Mail dispatch notice for recipient %s: %s", recipient, e)

        return {
            "dispatched": True,
            "recipient_count": len(all_recipients),
            "message": f"Email successfully dispatched to {len(all_recipients)} recipient(s).",
        }

    # =========================================================================
    # Formatting Helpers
    # =========================================================================

    def _format_message(self, msg: ConnectMessage, current_user_id: uuid.UUID) -> dict[str, Any]:
        """Format message entity with reaction aggregates and attachment data."""
        reactions_map: dict[str, list[uuid.UUID]] = {}
        for r in msg.reactions:
            if r.emoji not in reactions_map:
                reactions_map[r.emoji] = []
            reactions_map[r.emoji].append(r.user_id)

        reaction_items = [
            {
                "emoji": emoji,
                "count": len(uids),
                "users": uids,
                "has_reacted": current_user_id in uids,
            }
            for emoji, uids in reactions_map.items()
        ]

        attachment_items = [
            {
                "id": a.id,
                "file_name": a.file_name,
                "file_url": a.file_url,
                "file_type": a.file_type,
                "file_size": a.file_size,
            }
            for a in msg.attachments
        ]

        thread_replies_val = msg.__dict__.get("thread_replies") if hasattr(msg, "__dict__") else None
        if thread_replies_val is None and not hasattr(msg, "_sa_instance_state"):
            thread_replies_val = getattr(msg, "thread_replies", None)
        thread_count = len(thread_replies_val) if thread_replies_val else 0

        sender_avatar = (
            getattr(msg.sender, "profile_photo", None)
            or getattr(msg.sender, "profile_photo_url", None)
            if msg.sender else None
        )

        return {
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "channel_id": msg.channel_id,
            "sender_id": msg.sender_id,
            "sender_name": msg.sender.name if msg.sender else "Unknown",
            "sender_avatar": sender_avatar,
            "content": msg.content,
            "voice_url": msg.voice_url,
            "voice_duration": msg.voice_duration,
            "is_pinned": msg.is_pinned,
            "pinned_at": msg.pinned_at,
            "pinned_by": msg.pinned_by,
            "reply_to_id": msg.reply_to_id,
            "parent_message_id": msg.parent_message_id,
            "thread_count": thread_count,
            "reactions": reaction_items,
            "attachments": attachment_items,
            "is_deleted": msg.is_deleted,
            "created_at": msg.created_at,
            "updated_at": msg.updated_at,
        }

    def _format_channel_detail(self, ch: ConnectChannel, current_user_id: uuid.UUID) -> dict[str, Any]:
        """Format channel detail."""
        members = [
            {
                "id": m.id,
                "user_id": m.user_id,
                "name": m.user.name if m.user else "Unknown",
                "email": m.user.email if m.user else "",
                "avatar_url": getattr(m.user, "profile_photo", None) if m.user else None,
                "role": m.role,
                "joined_at": m.joined_at,
                "is_muted": m.is_muted,
            }
            for m in ch.members
        ]

        is_creator = ch.created_by == current_user_id
        is_host = any(m.user_id == current_user_id and m.role == "host" for m in ch.members)

        return {
            "id": ch.id,
            "name": ch.name,
            "description": ch.description,
            "is_private": ch.is_private,
            "is_archived": ch.is_archived,
            "created_by": ch.created_by,
            "host_info": {
                "id": ch.creator.id if ch.creator else ch.created_by,
                "name": ch.creator.name if ch.creator else "Host",
            },
            "members_count": len(ch.members),
            "members": members,
            "permissions": {
                "canPost": True,
                "canManage": is_creator or is_host,
                "canArchive": is_creator or is_host,
                "canInvite": True,
            },
            "created_at": ch.created_at,
            "updated_at": ch.updated_at,
        }

    def _format_meeting_detail(self, m: ConnectMeeting) -> dict[str, Any]:
        """Format meeting detail."""
        participants = [
            {
                "id": p.id,
                "user_id": p.user_id,
                "name": p.user.name if p.user else "Unknown",
                "email": p.user.email if p.user else "",
                "avatar_url": getattr(p.user, "profile_photo", None) if p.user else None,
                "role": p.role,
                "status": p.status,
                "joined_at": p.joined_at,
                "left_at": p.left_at,
            }
            for p in m.participants
        ]

        return {
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "meeting_code": m.meeting_code,
            "meeting_type": m.meeting_type,
            "status": m.status,
            "host_id": m.host_id,
            "host_name": m.host.name if m.host else "Host",
            "host_avatar": getattr(m.host, "profile_photo", None) if m.host else None,
            "start_time": m.start_time,
            "end_time": m.end_time,
            "duration_minutes": m.duration_minutes,
            "allow_screen_share": m.allow_screen_share,
            "allow_microphone": m.allow_microphone,
            "allow_camera": m.allow_camera,
            "is_private": m.is_private,
            "participants": participants,
            "join_url": f"/connect/meet/{m.meeting_code}",
            "created_at": m.created_at,
        }
