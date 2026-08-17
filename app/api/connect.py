"""FastAPI Router for OFC360 Connect Module containing all 40 required endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any
import uuid

from fastapi import (
    APIRouter, Depends, File, Header, HTTPException,
    Query, UploadFile, WebSocket, WebSocketDisconnect, status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException, UnauthorizedException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user, get_current_user_claims
from app.models.user import User
from app.schemas.connect import (
    AITransformRequest,
    CallInitiateRequest,
    CallSignalRequest,
    CallStatusUpdateRequest,
    ChannelAddMembersRequest,
    ChannelArchiveRequest,
    ChannelCreateRequest,
    ChannelUpdateRequest,
    ConversationCreateRequest,
    MailDispatchRequest,
    MeetingCreateRequest,
    MeetingLeaveRequest,
    MeetingMessageCreateRequest,
    MessagePinRequest,
    MessageReactionRequest,
    PresenceBatchRequest,
    PresenceUpdateRequest,
    SendMessageRequest,
    SoundSettingsUpdateRequest,
    ThreadReplyRequest,
)
from app.services.connect_service import ConnectService
from app.services.connect_ws_manager import get_connect_ws_manager
from app.utils.jwt import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connect", tags=["OFC360 Connect"])


def resolve_tenant_id(
    claims: dict[str, Any],
    user: User,
    x_company_id: str | None = None,
) -> uuid.UUID:
    """Validate and resolve tenant isolation company UUID."""
    user_company = user.company_id or claims.get("company_id")
    if not user_company:
        raise AppException(
            message="Authenticated user is not assigned to a company.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    user_company_uuid = uuid.UUID(str(user_company))

    if x_company_id and x_company_id.strip():
        try:
            header_uuid = uuid.UUID(x_company_id.strip())
            user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
            if header_uuid != user_company_uuid and user_role != "super_admin":
                logger.warning(
                    "Tenant ID mismatch attempt | user=%s header_tenant=%s user_tenant=%s",
                    user.id, header_uuid, user_company_uuid,
                )
                raise ForbiddenException("Access denied for the requested tenant.")
            return header_uuid
        except ValueError:
            raise AppException(message="Invalid X-Company-ID header.", status_code=status.HTTP_400_BAD_REQUEST)

    return user_company_uuid


# ===========================================================================
# A. USER DISCOVERY & DIRECTORY
# ===========================================================================

@router.get(
    "/colleagues",
    summary="1. User Discovery - List Colleagues",
    description="Fetch colleagues in the company directory with search, department filter, presence filter, and pagination.",
)
async def get_colleagues(
    search: str | None = Query(None, description="Search by name, email, or designation"),
    department: str | None = Query(None, description="Filter by department"),
    presence: str | None = Query(None, description="Filter by presence status: online, away, busy, dnd, offline"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_colleagues(
        company_id=company_id,
        search=search,
        department=department,
        presence_filter=presence,
        page=page,
        limit=limit,
        exclude_user_id=user.id,
    )
    return {
        "success": True,
        "message": "Colleagues retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/search",
    summary="2. Unified Search",
    description="Unified search across people, channels, messages, and files.",
)
async def unified_search(
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.unified_search(
        company_id=company_id,
        user_id=user.id,
        query=q,
        limit=limit,
    )
    return {
        "success": True,
        "message": "Search completed successfully",
        "data": result,
        "errors": None,
    }


# ===========================================================================
# B. DIRECT MESSAGING & CONVERSATIONS
# ===========================================================================

@router.get(
    "/conversations",
    summary="3. Get Conversations",
    description="Fetch all direct conversations for the authenticated user.",
)
async def get_conversations(
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_conversations(company_id=company_id, user_id=user.id)
    return {
        "success": True,
        "message": "Conversations retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/conversations",
    summary="4. Create or Retrieve Direct Conversation",
    description="Idempotently create or retrieve a direct message conversation with target user.",
    status_code=status.HTTP_200_OK,
)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_or_create_conversation(
        company_id=company_id,
        user=user,
        target_user_id=payload.targetUserId,
    )
    return {
        "success": True,
        "message": "Conversation retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/conversations/{conversationId}/messages",
    summary="5. Get Conversation Messages",
    description="Fetch messages from a conversation with cursor pagination and search.",
)
async def get_conversation_messages(
    conversationId: uuid.UUID,
    search: str | None = Query(None),
    before: uuid.UUID | None = Query(None),
    after: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_conversation_messages(
        company_id=company_id,
        user=user,
        conversation_id=conversationId,
        query=search,
        before_id=before,
        after_id=after,
        limit=limit,
    )
    return {
        "success": True,
        "message": "Messages retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/conversations/{conversationId}/messages",
    summary="6. Send Conversation Message",
    description="Send a message (text, attachments, voice) in a conversation.",
    status_code=status.HTTP_201_CREATED,
)
async def send_conversation_message(
    conversationId: uuid.UUID,
    payload: SendMessageRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    attachments_data = [a.model_dump() for a in payload.attachments] if payload.attachments else []
    result = await service.send_conversation_message(
        company_id=company_id,
        user=user,
        conversation_id=conversationId,
        text=payload.text,
        attachments=attachments_data,
        voice_url=payload.voiceUrl,
        voice_duration=payload.voiceDuration,
        reply_to_id=payload.replyToMessageId,
    )
    return {
        "success": True,
        "message": "Message sent successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/messages/{messageId}/reactions",
    summary="7. Toggle Message Reaction",
    description="Add or remove an emoji reaction on a message.",
)
async def toggle_reaction(
    messageId: uuid.UUID,
    payload: MessageReactionRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.toggle_message_reaction(
        company_id=company_id,
        user=user,
        message_id=messageId,
        emoji=payload.emoji,
    )
    return {
        "success": True,
        "message": "Reaction updated successfully",
        "data": result,
        "errors": None,
    }


@router.patch(
    "/messages/{messageId}/pin",
    summary="8. Pin/Unpin Message",
    description="Pin or unpin a message in its conversation or channel.",
)
async def pin_message(
    messageId: uuid.UUID,
    payload: MessagePinRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.toggle_message_pin(
        company_id=company_id,
        user=user,
        message_id=messageId,
        is_pinned=payload.isPinned,
    )
    return {
        "success": True,
        "message": "Message pin status updated",
        "data": result,
        "errors": None,
    }


@router.delete(
    "/messages/{messageId}",
    summary="9. Delete Message",
    description="Soft delete a message (allowed for owner, hr_admin, or super_admin).",
)
async def delete_message(
    messageId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.delete_message(
        company_id=company_id,
        user=user,
        message_id=messageId,
    )
    return {
        "success": True,
        "message": "Message deleted successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/messages/{parentMessageId}/thread",
    summary="10. Get Message Thread",
    description="Fetch all replies in a message thread.",
)
async def get_message_thread(
    parentMessageId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_message_thread(
        company_id=company_id,
        user=user,
        parent_message_id=parentMessageId,
    )
    return {
        "success": True,
        "message": "Thread replies retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/messages/{parentMessageId}/thread",
    summary="11. Post Thread Reply",
    description="Post a reply in a message thread.",
    status_code=status.HTTP_201_CREATED,
)
async def post_thread_reply(
    parentMessageId: uuid.UUID,
    payload: ThreadReplyRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    attachments_data = [a.model_dump() for a in payload.attachments] if payload.attachments else []
    result = await service.post_thread_reply(
        company_id=company_id,
        user=user,
        parent_message_id=parentMessageId,
        text=payload.text,
        attachments=attachments_data,
        voice_url=payload.voiceUrl,
        voice_duration=payload.voiceDuration,
    )
    return {
        "success": True,
        "message": "Thread reply posted successfully",
        "data": result,
        "errors": None,
    }


# ===========================================================================
# C. TEAM CHANNELS
# ===========================================================================

@router.get(
    "/channels",
    summary="12. Get Channels",
    description="Fetch team channels with search support.",
)
async def get_channels(
    search: str | None = Query(None, description="Search by channel name"),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_channels(company_id=company_id, user=user, query=search)
    return {
        "success": True,
        "message": "Channels retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/channels",
    summary="13. Create Channel",
    description="Create a new team channel.",
    status_code=status.HTTP_201_CREATED,
)
async def create_channel(
    payload: ChannelCreateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.create_channel(
        company_id=company_id,
        user=user,
        name=payload.name,
        description=payload.description,
        is_private=payload.isPrivate,
        member_ids=payload.memberIds,
    )
    return {
        "success": True,
        "message": "Channel created successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/channels/{channelId}",
    summary="14. Get Channel Details",
    description="Fetch channel details, members, host, and permissions.",
)
async def get_channel_detail(
    channelId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_channel_detail(
        company_id=company_id,
        user=user,
        channel_id=channelId,
    )
    return {
        "success": True,
        "message": "Channel details retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.patch(
    "/channels/{channelId}",
    summary="14b. Update Channel",
    description="Update team channel name, description, privacy, or archive status (Creator, Host, or Admin).",
)
async def update_channel(
    channelId: uuid.UUID,
    payload: ChannelUpdateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.update_channel(
        company_id=company_id,
        user=user,
        channel_id=channelId,
        name=payload.name,
        description=payload.description,
        is_private=payload.isPrivate,
        is_archived=payload.isArchived,
    )
    return {
        "success": True,
        "message": "Channel updated successfully",
        "data": result,
        "errors": None,
    }


@router.delete(
    "/channels/{channelId}",
    summary="14c. Delete Channel",
    description="Soft delete a team channel (Creator, Host, or Admin).",
)
async def delete_channel(
    channelId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.delete_channel(
        company_id=company_id,
        user=user,
        channel_id=channelId,
    )
    return {
        "success": True,
        "message": "Channel deleted successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/channels/{channelId}/members",
    summary="14d. Add Channel Members",
    description="Add new members to a team channel.",
)
async def add_channel_members(
    channelId: uuid.UUID,
    payload: ChannelAddMembersRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.add_channel_members(
        company_id=company_id,
        user=user,
        channel_id=channelId,
        member_ids=payload.memberIds,
    )
    return {
        "success": True,
        "message": "Members added to channel successfully",
        "data": result,
        "errors": None,
    }


@router.delete(
    "/channels/{channelId}/members/{userId}",
    summary="14e. Remove Channel Member",
    description="Remove a member from a team channel (Self, Creator, Host, or Admin).",
)
async def remove_channel_member(
    channelId: uuid.UUID,
    userId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.remove_channel_member(
        company_id=company_id,
        user=user,
        channel_id=channelId,
        target_user_id=userId,
    )
    return {
        "success": True,
        "message": "Member removed from channel successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/channels/{channelId}/messages",
    summary="15. Get Channel Messages",
    description="Fetch messages from a channel with cursor pagination and search.",
)
async def get_channel_messages(
    channelId: uuid.UUID,
    search: str | None = Query(None),
    pinnedOnly: bool = Query(False),
    before: uuid.UUID | None = Query(None),
    after: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_channel_messages(
        company_id=company_id,
        user=user,
        channel_id=channelId,
        query=search,
        pinned_only=pinnedOnly,
        before_id=before,
        after_id=after,
        limit=limit,
    )
    return {
        "success": True,
        "message": "Channel messages retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/channels/{channelId}/messages",
    summary="16. Send Channel Message",
    description="Send message to a channel.",
    status_code=status.HTTP_201_CREATED,
)
async def send_channel_message(
    channelId: uuid.UUID,
    payload: SendMessageRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    attachments_data = [a.model_dump() for a in payload.attachments] if payload.attachments else []
    result = await service.send_channel_message(
        company_id=company_id,
        user=user,
        channel_id=channelId,
        text=payload.text,
        attachments=attachments_data,
        voice_url=payload.voiceUrl,
        voice_duration=payload.voiceDuration,
        reply_to_id=payload.replyToMessageId,
    )
    return {
        "success": True,
        "message": "Channel message sent successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/channels/{channelId}/leave",
    summary="17. Leave Channel",
    description="Leave a team channel.",
)
async def leave_channel(
    channelId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.leave_channel(
        company_id=company_id,
        user=user,
        channel_id=channelId,
    )
    return {
        "success": True,
        "message": "Left channel successfully",
        "data": result,
        "errors": None,
    }


@router.patch(
    "/channels/{channelId}/archive",
    summary="18. Archive Channel",
    description="Archive or unarchive a channel (Creator or Admin).",
)
async def archive_channel(
    channelId: uuid.UUID,
    payload: ChannelArchiveRequest = ChannelArchiveRequest(isArchived=True),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.archive_channel(
        company_id=company_id,
        user=user,
        channel_id=channelId,
        is_archived=payload.isArchived,
    )
    return {
        "success": True,
        "message": "Channel archive status updated",
        "data": result,
        "errors": None,
    }


# ===========================================================================
# D. CALLS & WEBRTC
# ===========================================================================

@router.get(
    "/calls/ice-servers",
    summary="19a. Get ICE Servers",
    description="Fetch WebRTC STUN/TURN server configuration for peer connections.",
)
async def get_ice_servers(
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = service.get_ice_servers()
    return {
        "success": True,
        "message": "ICE servers retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/calls/history",
    summary="19. Get Call History",
    description="Fetch audio and video call history for the authenticated user.",
)
async def get_call_history(
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_call_history(company_id=company_id, user=user, limit=limit)
    return {
        "success": True,
        "message": "Call history retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/calls/{callId}",
    summary="20a. Get Call Details",
    description="Fetch call session details, duration, timestamps, and participants.",
)
async def get_call_detail(
    callId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_call_detail(
        company_id=company_id,
        user=user,
        call_id=callId,
    )
    return {
        "success": True,
        "message": "Call details retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/calls/initiate",
    summary="20. Initiate Call",
    description="Initiate an audio or video call session with target user.",
    status_code=status.HTTP_201_CREATED,
)
async def initiate_call(
    payload: CallInitiateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.initiate_call(
        company_id=company_id,
        user=user,
        target_user_id=payload.targetUserId,
        call_type=payload.type,
    )
    return {
        "success": True,
        "message": "Call initiated successfully",
        "data": result,
        "errors": None,
    }


@router.patch(
    "/calls/{callId}/status",
    summary="21. Update Call Status",
    description="Update call status: connected, rejected, ended, missed, failed.",
)
async def update_call_status(
    callId: uuid.UUID,
    payload: CallStatusUpdateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.update_call_status(
        company_id=company_id,
        user=user,
        call_id=callId,
        new_status=payload.status,
    )
    return {
        "success": True,
        "message": "Call status updated successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/calls/{callId}/signal",
    summary="22. WebRTC Signaling Relay",
    description="Relay WebRTC signaling packets (offer, answer, ICE candidate) via server without passing media.",
)
async def call_signal(
    callId: uuid.UUID,
    payload: CallSignalRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.handle_call_signal(
        company_id=company_id,
        user=user,
        call_id=callId,
        signal_type=payload.type,
        payload=payload.payload,
        target_user_id=payload.targetUserId,
    )
    return {
        "success": True,
        "message": "Signal relayed successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# E. VIDEO MEETINGS
# =========================================================================

@router.get(
    "/meetings",
    summary="23. Get Meetings",
    description="Fetch upcoming, live, and past video meetings for current user.",
)
async def get_meetings(
    status_filter: str | None = Query(None, alias="status"),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_meetings(company_id=company_id, user=user, status_filter=status_filter)
    return {
        "success": True,
        "message": "Meetings retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/meetings",
    summary="24. Create Meeting",
    description="Create an instant or scheduled video meeting with participant controls.",
    status_code=status.HTTP_201_CREATED,
)
async def create_meeting(
    payload: MeetingCreateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.create_meeting(
        company_id=company_id,
        user=user,
        title=payload.title,
        description=payload.description,
        meeting_type=payload.type,
        start_time=payload.startTime,
        duration_minutes=payload.duration,
        participant_ids=payload.participantIds,
        allow_screen_share=payload.allowScreenShare,
        allow_microphone=payload.allowMicrophone,
        allow_camera=payload.allowCamera,
        is_private=payload.isPrivate,
    )
    return {
        "success": True,
        "message": "Meeting created successfully",
        "data": result,
        "errors": None,
    }


@router.get(
    "/meetings/{meetingId}",
    summary="25. Get Meeting Details",
    description="Fetch meeting details, participants, permissions, and host info.",
)
async def get_meeting_detail(
    meetingId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_meeting_detail(
        company_id=company_id,
        user=user,
        meeting_id=meetingId,
    )
    return {
        "success": True,
        "message": "Meeting details retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/meetings/{meetingId}/join",
    summary="26. Join Meeting",
    description="Join a video meeting as a participant.",
)
async def join_meeting(
    meetingId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.join_meeting(
        company_id=company_id,
        user=user,
        meeting_id=meetingId,
    )
    return {
        "success": True,
        "message": "Joined meeting successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/meetings/{meetingId}/leave",
    summary="27. Leave Meeting",
    description="Leave meeting or end meeting for everyone (host only).",
)
async def leave_meeting(
    meetingId: uuid.UUID,
    payload: MeetingLeaveRequest = MeetingLeaveRequest(endForEveryone=False),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.leave_meeting(
        company_id=company_id,
        user=user,
        meeting_id=meetingId,
        end_for_everyone=payload.endForEveryone,
    )
    return {
        "success": True,
        "message": "Meeting status updated",
        "data": result,
        "errors": None,
    }


@router.post(
    "/meetings/{meetingId}/messages",
    summary="28. Send Meeting Message",
    description="Send chat message inside a meeting.",
    status_code=status.HTTP_201_CREATED,
)
async def send_meeting_message(
    meetingId: uuid.UUID,
    payload: MeetingMessageCreateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.send_meeting_message(
        company_id=company_id,
        user=user,
        meeting_id=meetingId,
        content=payload.message,
    )
    return {
        "success": True,
        "message": "Meeting message sent successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# F. SHARED FILES
# =========================================================================

@router.get(
    "/files",
    summary="29. Get Shared Files",
    description="Fetch shared files with filtering (all, shared_with_me, shared_by_me, recent, images, videos, documents, spreadsheets) and search.",
)
async def get_shared_files(
    filter: str = Query("all", description="all, shared_by_me, images, videos, documents, spreadsheets"),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_shared_files(
        company_id=company_id,
        user=user,
        filter_type=filter,
        search=search,
        page=page,
        limit=limit,
    )
    return {
        "success": True,
        "message": "Shared files retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/files/upload",
    summary="30. Upload Shared File",
    description="Upload a shared file (multipart/form-data) with validation of type, size, and tenant.",
    status_code=status.HTTP_201_CREATED,
)
async def upload_shared_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.upload_shared_file(
        company_id=company_id,
        user=user,
        file=file,
    )
    return {
        "success": True,
        "message": "File uploaded successfully",
        "data": result,
        "errors": None,
    }


@router.delete(
    "/files/{fileId}",
    summary="31. Delete Shared File",
    description="Delete a shared file (Uploader or Admin).",
)
async def delete_shared_file(
    fileId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.delete_shared_file(
        company_id=company_id,
        user=user,
        file_id=fileId,
    )
    return {
        "success": True,
        "message": "File deleted successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# G. PRESENCE
# =========================================================================

@router.put(
    "/presence",
    summary="32. Update User Presence",
    description="Update user presence status (online, away, busy, dnd, offline) and optional custom status.",
)
async def update_presence(
    payload: PresenceUpdateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.update_presence(
        company_id=company_id,
        user=user,
        pres_status=payload.status,
        custom_status=payload.customStatus,
    )
    return {
        "success": True,
        "message": "Presence updated successfully",
        "data": result,
        "errors": None,
    }


@router.post(
    "/presence/batch",
    summary="33. Batch Presence Lookup",
    description="Fetch real-time presence indicators for multiple users.",
)
async def batch_presence(
    payload: PresenceBatchRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_batch_presence(
        company_id=company_id,
        user_ids=payload.userIds,
    )
    return {
        "success": True,
        "message": "Presence batch retrieved successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# H. NOTIFICATIONS
# =========================================================================

@router.get(
    "/notifications",
    summary="34. Get Notifications",
    description="Fetch notifications for current user with unread filter.",
)
async def get_notifications(
    unreadOnly: bool = Query(False),
    type: str | None = Query(None, description="message, mention, call, meeting, file, channel"),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_notifications(
        company_id=company_id,
        user=user,
        unread_only=unreadOnly,
        limit=limit,
        notification_type=type,
    )
    return {
        "success": True,
        "message": "Notifications retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.patch(
    "/notifications/{notificationId}/read",
    summary="35. Mark Notification as Read",
    description="Mark a notification as read.",
)
async def mark_notification_read(
    notificationId: uuid.UUID,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.mark_notification_read(
        company_id=company_id,
        user=user,
        notification_id=notificationId,
    )
    return {
        "success": True,
        "message": "Notification marked as read",
        "data": result,
        "errors": None,
    }


@router.delete(
    "/notifications",
    summary="36. Clear Notifications",
    description="Clear all notifications for the current user.",
)
async def clear_notifications(
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.delete_notifications(company_id=company_id, user=user)
    return {
        "success": True,
        "message": "Notifications cleared successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# I. SOUND SETTINGS
# =========================================================================

@router.get(
    "/settings/sound",
    summary="37. Get Sound Settings",
    description="Fetch audio feedback, master volume, and notification tone settings.",
)
async def get_sound_settings(
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.get_sound_settings(company_id=company_id, user=user)
    return {
        "success": True,
        "message": "Sound settings retrieved successfully",
        "data": result,
        "errors": None,
    }


@router.put(
    "/settings/sound",
    summary="38. Update Sound Settings",
    description="Persist user sound settings.",
)
async def update_sound_settings(
    payload: SoundSettingsUpdateRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.update_sound_settings(
        company_id=company_id,
        user=user,
        master_volume=payload.masterVolume,
        is_muted=payload.isMuted,
        incoming_call_chime=payload.incomingCallChime,
        outgoing_call_chime=payload.outgoingCallChime,
        message_chime=payload.messageChime,
        mention_chime=payload.mentionChime,
        meeting_chime=payload.meetingChime,
        ringtone=payload.ringtone,
        notification_tone=payload.notificationTone,
    )
    return {
        "success": True,
        "message": "Sound settings updated successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# J. AI COPILOT
# =========================================================================

@router.post(
    "/ai/transform",
    summary="39. AI Communication Copilot Transform",
    description="Transform text: professional, generate_reply, tone (friendly, diplomatic, urgent), shorten, expand, summarize.",
)
async def ai_transform(
    payload: AITransformRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    result = await service.transform_ai(
        text=payload.text,
        action=payload.action,
        tone=payload.tone,
        context=payload.context,
    )
    return {
        "success": True,
        "message": "AI transformation completed successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# K. MAIL DISPATCH
# =========================================================================

@router.post(
    "/mail/dispatch",
    summary="40. Connect Mail Dispatch",
    description="Send email with authenticated user identity and recipient validation.",
)
async def mail_dispatch(
    payload: MailDispatchRequest,
    user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
    x_company_id: str | None = Header(None, alias="X-Company-ID"),
):
    company_id = resolve_tenant_id(claims, user, x_company_id)
    service = ConnectService(db)
    attachments_data = [a.model_dump() for a in payload.attachments] if payload.attachments else []
    result = await service.dispatch_mail(
        company_id=company_id,
        user=user,
        to=[str(e) for e in payload.to],
        subject=payload.subject,
        body=payload.body,
        cc=[str(e) for e in payload.cc] if payload.cc else None,
        bcc=[str(e) for e in payload.bcc] if payload.bcc else None,
        attachments=attachments_data,
    )
    return {
        "success": True,
        "message": "Mail dispatched successfully",
        "data": result,
        "errors": None,
    }


# =========================================================================
# REAL-TIME WEBSOCKET ENDPOINT
# =========================================================================

@router.websocket("/ws")
async def connect_websocket(
    websocket: WebSocket,
    token: str | None = Query(None),
):
    """WebSocket endpoint for Connect real-time events, typing indicators, presence, and WebRTC signaling."""
    # Authenticate token from query parameter or authorization header
    auth_token = token
    if not auth_token:
        auth_header = websocket.headers.get("authorization") or websocket.headers.get("sec-websocket-protocol")
        if auth_header and "bearer " in auth_header.lower():
            auth_token = auth_header.split(" ", 1)[1].strip()

    if not auth_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication token required.")
        return

    try:
        claims = decode_token(auth_token)
        user_id = uuid.UUID(str(claims.get("sub")))
        company_id = uuid.UUID(str(claims.get("company_id")))
    except Exception as e:
        logger.warning("WebSocket token verification failed: %s", e)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token.")
        return

    ws_manager = get_connect_ws_manager()
    await websocket.accept()
    await ws_manager.connect(websocket, user_id, company_id)

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                try:
                    await websocket.send_json({"event": "error", "data": {"message": "Invalid JSON frame received."}})
                except Exception:
                    break
                continue

            if not isinstance(data, dict):
                continue

            event = data.get("event")
            payload = data.get("data", {})
            if not isinstance(payload, dict):
                payload = {}

            if event == "ping":
                await websocket.send_json({"event": "pong", "timestamp": data.get("timestamp")})

            elif event == "join_room":
                room_id = payload.get("room_id")
                if room_id:
                    await ws_manager.join_room(user_id, room_id)
                    await websocket.send_json({"event": "room_joined", "data": {"room_id": room_id}})

            elif event == "leave_room":
                room_id = payload.get("room_id")
                if room_id:
                    await ws_manager.leave_room(user_id, room_id)
                    await websocket.send_json({"event": "room_left", "data": {"room_id": room_id}})

            elif event == "typing":
                target_room = payload.get("room_id")
                target_user = payload.get("target_user_id")
                typing_data = {"user_id": str(user_id), "is_typing": payload.get("is_typing", True)}

                if target_room:
                    await ws_manager.send_to_room(target_room, company_id, "typing", typing_data, exclude_user_id=user_id)
                elif target_user:
                    try:
                        target_uuid = uuid.UUID(str(target_user))
                        await ws_manager.send_to_user(target_uuid, company_id, "typing", typing_data)
                    except ValueError:
                        pass

            elif event in ("webrtc:signal", "call_signal", "signal"):
                target_user = (
                    payload.get("targetUserId")
                    or payload.get("target_user_id")
                    or payload.get("recipientId")
                    or payload.get("recipient_id")
                )
                if target_user:
                    try:
                        target_uuid = uuid.UUID(str(target_user))
                        sig_type = payload.get("type")
                        if not sig_type and isinstance(payload.get("signal"), dict):
                            sig_type = payload["signal"].get("type")
                        if not sig_type and isinstance(payload.get("payload"), dict):
                            sig_type = payload["payload"].get("type")

                        signal_payload = {
                            "call_id": payload.get("callId") or payload.get("call_id"),
                            "callId": payload.get("callId") or payload.get("call_id"),
                            "from_user_id": str(user_id),
                            "fromUserId": str(user_id),
                            "target_user_id": str(target_uuid),
                            "targetUserId": str(target_uuid),
                            "type": sig_type or "signal",
                            "payload": payload.get("payload") or payload.get("signal") or payload,
                            "signal": payload.get("signal") or payload.get("payload") or payload,
                        }
                        if "sdp" in payload:
                            signal_payload["sdp"] = payload["sdp"]
                        if "candidate" in payload:
                            signal_payload["candidate"] = payload["candidate"]

                        await ws_manager.send_to_user(target_uuid, company_id, "webrtc:signal", signal_payload)
                        await ws_manager.send_to_user(target_uuid, company_id, "call_signal", signal_payload)
                    except ValueError:
                        pass

            elif event in ("call:accept", "call:accepted", "call:reject", "call:rejected", "call:end", "call:ended"):
                target_user = (
                    payload.get("targetUserId")
                    or payload.get("target_user_id")
                    or payload.get("recipientId")
                    or payload.get("recipient_id")
                    or payload.get("otherUserId")
                )
                if target_user:
                    try:
                        target_uuid = uuid.UUID(str(target_user))
                        normalized_event = "call:accepted" if "accept" in event else ("call:rejected" if "reject" in event else "call:ended")
                        await ws_manager.send_to_user(target_uuid, company_id, normalized_event, payload)
                        await ws_manager.send_to_user(target_uuid, company_id, "call_status_changed", payload)
                    except ValueError:
                        pass

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket error for user %s: %s", user_id, e)
        await ws_manager.disconnect(websocket)
