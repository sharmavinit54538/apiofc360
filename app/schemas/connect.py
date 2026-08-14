"""Pydantic v2 schemas for the OFC360 Connect Module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# ===========================================================================
# Standard Envelope Models (Matching OFC360 Convention)
# ===========================================================================

class ConnectStandardResponse(BaseModel):
    """Standard unified response envelope for Connect module."""
    success: bool = True
    message: str = "Operation successful"
    data: Any = None
    errors: Any = None


# ===========================================================================
# A. User Discovery & Directory Schemas
# ===========================================================================

class ColleagueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    phone: str | None = None
    role: str
    department: str | None = None
    designation: str | None = None
    avatar_url: str | None = None
    presence_status: str = "offline"  # online, away, busy, dnd, offline
    custom_status: str | None = None
    last_seen_at: datetime | None = None


class ColleaguesListResponse(BaseModel):
    colleagues: list[ColleagueItemResponse]
    total: int
    page: int
    limit: int


class ChannelSearchItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_private: bool = False
    members_count: int = 0


class MessageSearchItem(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    sender_id: uuid.UUID
    sender_name: str
    content: str | None = None
    created_at: datetime


class FileSearchItem(BaseModel):
    id: uuid.UUID
    file_name: str
    file_url: str
    file_type: str
    file_size: int
    uploader_name: str
    created_at: datetime


class UnifiedSearchResponse(BaseModel):
    people: list[ColleagueItemResponse] = []
    channels: list[ChannelSearchItem] = []
    messages: list[MessageSearchItem] = []
    files: list[FileSearchItem] = []


# ===========================================================================
# B. Direct Messaging Schemas
# ===========================================================================

class ConversationCreateRequest(BaseModel):
    targetUserId: uuid.UUID = Field(..., description="ID of the user to start conversation with")


class ConversationParticipantResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    avatar_url: str | None = None
    role: str
    presence_status: str = "offline"
    is_muted: bool = False
    last_read_at: datetime | None = None


class ConversationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    participants: list[ConversationParticipantResponse] = []
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class MessageAttachmentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    file_url: str
    file_type: str
    file_size: int


class MessageReactionItem(BaseModel):
    emoji: str
    count: int
    users: list[uuid.UUID]
    has_reacted: bool = False


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    channel_id: uuid.UUID | None = None
    sender_id: uuid.UUID
    sender_name: str
    sender_avatar: str | None = None
    content: str | None = None
    voice_url: str | None = None
    voice_duration: int | None = None
    is_pinned: bool = False
    pinned_at: datetime | None = None
    pinned_by: uuid.UUID | None = None
    reply_to_id: uuid.UUID | None = None
    parent_message_id: uuid.UUID | None = None
    thread_count: int = 0
    reactions: list[MessageReactionItem] = []
    attachments: list[MessageAttachmentItem] = []
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class AttachmentInput(BaseModel):
    fileName: str
    fileUrl: str
    fileType: str
    fileSize: int = 0


class SendMessageRequest(BaseModel):
    text: str | None = None
    attachments: list[AttachmentInput] = []
    voiceUrl: str | None = None
    voiceDuration: int | None = None
    replyToMessageId: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_content_presence(self) -> SendMessageRequest:
        if not self.text and not self.attachments and not self.voiceUrl:
            raise ValueError("Message must contain text, an attachment, or a voice message.")
        return self


class MessageReactionRequest(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=50)


class MessagePinRequest(BaseModel):
    isPinned: bool = True


class ThreadReplyRequest(BaseModel):
    text: str | None = None
    attachments: list[AttachmentInput] = []
    voiceUrl: str | None = None
    voiceDuration: int | None = None

    @model_validator(mode="after")
    def validate_thread_content(self) -> ThreadReplyRequest:
        if not self.text and not self.attachments and not self.voiceUrl:
            raise ValueError("Thread reply must contain text, an attachment, or a voice message.")
        return self


# ===========================================================================
# C. Team Channels Schemas
# ===========================================================================

class ChannelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    isPrivate: bool = False
    memberIds: list[uuid.UUID] = []


class ChannelMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    avatar_url: str | None = None
    role: str  # host, admin, member
    joined_at: datetime
    is_muted: bool = False


class ChannelPermissions(BaseModel):
    canPost: bool = True
    canManage: bool = False
    canArchive: bool = False
    canInvite: bool = True


class ChannelDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    is_private: bool = False
    is_archived: bool = False
    created_by: uuid.UUID
    host_info: dict[str, Any] | None = None
    members_count: int = 0
    members: list[ChannelMemberResponse] = []
    permissions: ChannelPermissions = Field(default_factory=ChannelPermissions)
    created_at: datetime
    updated_at: datetime


class ChannelItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    is_private: bool = False
    is_archived: bool = False
    created_by: uuid.UUID
    members_count: int = 0
    unread_count: int = 0
    is_member: bool = False
    created_at: datetime
    updated_at: datetime


class ChannelArchiveRequest(BaseModel):
    isArchived: bool = True


# ===========================================================================
# D. Calls & WebRTC Schemas
# ===========================================================================

class CallInitiateRequest(BaseModel):
    targetUserId: uuid.UUID
    type: Literal["audio", "video"] = "audio"


class CallInitiateResponse(BaseModel):
    id: uuid.UUID
    caller_id: uuid.UUID
    callee_id: uuid.UUID
    call_type: str
    status: str
    room_id: str
    started_at: datetime


class CallStatusUpdateRequest(BaseModel):
    status: Literal["connected", "rejected", "ended", "missed", "failed"]


class CallHistoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caller_id: uuid.UUID
    caller_name: str
    caller_avatar: str | None = None
    callee_id: uuid.UUID
    callee_name: str
    callee_avatar: str | None = None
    call_type: str
    status: str
    room_id: str
    duration_seconds: int
    started_at: datetime
    connected_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime


class CallSignalRequest(BaseModel):
    type: Literal["offer", "answer", "ice-candidate"]
    payload: dict[str, Any]
    targetUserId: uuid.UUID | None = None


# ===========================================================================
# E. Video Meetings Schemas
# ===========================================================================

class MeetingCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    type: Literal["instant", "scheduled"] = "instant"
    startTime: datetime | None = None
    duration: int = Field(30, ge=5, le=1440, description="Duration in minutes")
    participantIds: list[uuid.UUID] = []
    allowScreenShare: bool = True
    allowMicrophone: bool = True
    allowCamera: bool = True
    isPrivate: bool = False


class MeetingParticipantItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    avatar_url: str | None = None
    role: str  # host, co-host, participant
    status: str  # invited, joined, left, declined
    joined_at: datetime | None = None
    left_at: datetime | None = None


class MeetingDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    meeting_code: str
    meeting_type: str
    status: str
    host_id: uuid.UUID
    host_name: str
    host_avatar: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_minutes: int
    allow_screen_share: bool
    allow_microphone: bool
    allow_camera: bool
    is_private: bool
    participants: list[MeetingParticipantItem] = []
    join_url: str
    created_at: datetime


class MeetingLeaveRequest(BaseModel):
    endForEveryone: bool = False


class MeetingMessageCreateRequest(BaseModel):
    message: str = Field(..., min_length=1)
    type: str = "chat"


class MeetingMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meeting_id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    sender_avatar: str | None = None
    content: str
    created_at: datetime


# ===========================================================================
# F. Shared Files Schemas
# ===========================================================================

class SharedFileItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    file_url: str
    file_type: str
    file_category: str
    file_size: int
    uploader_id: uuid.UUID
    uploader_name: str
    created_at: datetime


class SharedFilesListResponse(BaseModel):
    files: list[SharedFileItemResponse]
    total: int
    page: int
    limit: int


# ===========================================================================
# G. Presence Schemas
# ===========================================================================

class PresenceUpdateRequest(BaseModel):
    status: Literal["online", "away", "busy", "dnd", "offline"]
    customStatus: str | None = Field(None, max_length=255)


class PresenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    status: str
    custom_status: str | None = None
    last_seen_at: datetime
    updated_at: datetime


class PresenceBatchRequest(BaseModel):
    userIds: list[uuid.UUID]


# ===========================================================================
# H. Notifications Schemas
# ===========================================================================

class ConnectNotificationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notification_type: str  # message, mention, call, meeting, file, channel
    title: str
    body: str
    resource_type: str | None = None
    resource_id: str | None = None
    is_read: bool
    read_at: datetime | None = None
    sender_id: uuid.UUID | None = None
    sender_name: str | None = None
    created_at: datetime


class ConnectNotificationReadResponse(BaseModel):
    id: uuid.UUID
    is_read: bool
    read_at: datetime | None = None


# ===========================================================================
# I. Sound Settings Schemas
# ===========================================================================

class SoundSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    masterVolume: int = 80
    isMuted: bool = False
    incomingCallChime: bool = True
    outgoingCallChime: bool = True
    messageChime: bool = True
    mentionChime: bool = True
    meetingChime: bool = True
    ringtone: str = "aurix_default_ringtone.mp3"
    notificationTone: str = "aurix_default_notification.mp3"


class SoundSettingsUpdateRequest(BaseModel):
    masterVolume: int = Field(80, ge=0, le=100)
    isMuted: bool = False
    incomingCallChime: bool = True
    outgoingCallChime: bool = True
    messageChime: bool = True
    mentionChime: bool = True
    meetingChime: bool = True
    ringtone: str = "aurix_default_ringtone.mp3"
    notificationTone: str = "aurix_default_notification.mp3"


# ===========================================================================
# J. AI Copilot Schemas
# ===========================================================================

class AITransformRequest(BaseModel):
    text: str = Field(..., min_length=1)
    action: Literal["professional", "generate_reply", "tone", "shorten", "expand", "summarize"]
    tone: Literal["friendly", "diplomatic", "urgent"] | None = None
    context: str | None = None


class AITransformResponse(BaseModel):
    original_text: str
    transformed_text: str
    action: str
    tone: str | None = None


# ===========================================================================
# K. Mail Dispatch Schemas
# ===========================================================================

class MailAttachmentInput(BaseModel):
    fileName: str
    fileUrl: str
    fileType: str | None = None


class MailDispatchRequest(BaseModel):
    to: list[EmailStr] = Field(..., min_length=1)
    cc: list[EmailStr] | None = None
    bcc: list[EmailStr] | None = None
    subject: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    attachments: list[MailAttachmentInput] | None = None


class MailDispatchResponse(BaseModel):
    dispatched: bool
    recipient_count: int
    message: str
