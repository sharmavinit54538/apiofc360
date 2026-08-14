"""Pydantic v2 schemas for the OFC360 Connect Module with complete frontend-backend contract normalization."""

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

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            target_id = (
                data.get("targetUserId")
                or data.get("target_user_id")
                or data.get("recipientId")
                or data.get("recipient_id")
                or data.get("userId")
                or data.get("user_id")
            )
            if target_id is not None:
                data["targetUserId"] = target_id
        return data


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
    fileType: str = "application/octet-stream"
    fileSize: int = 0

    @model_validator(mode="before")
    @classmethod
    def normalize_attachment(cls, data: Any) -> Any:
        if isinstance(data, dict):
            file_name = data.get("fileName") or data.get("file_name") or data.get("name") or "attachment"
            file_url = data.get("fileUrl") or data.get("file_url") or data.get("url") or ""
            file_type = data.get("fileType") or data.get("file_type") or data.get("type") or "application/octet-stream"
            file_size = data.get("fileSize") or data.get("file_size") or data.get("size") or 0
            return {
                "fileName": str(file_name),
                "fileUrl": str(file_url),
                "fileType": str(file_type),
                "fileSize": int(file_size) if str(file_size).isdigit() else 0,
            }
        return data


class SendMessageRequest(BaseModel):
    text: str | None = None
    attachments: list[AttachmentInput] = []
    voiceUrl: str | None = None
    voiceDuration: int | None = None
    replyToMessageId: uuid.UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_message_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Resolve text / content / message / body
            text_val = data.get("text")
            if text_val is None:
                text_val = data.get("content") or data.get("message") or data.get("body")
            data["text"] = text_val

            # Resolve voiceUrl / voice_url / audioUrl / audio_url
            voice_url = data.get("voiceUrl") or data.get("voice_url") or data.get("audioUrl") or data.get("audio_url")
            data["voiceUrl"] = voice_url

            # Resolve voiceDuration / voice_duration / duration
            voice_dur = data.get("voiceDuration") or data.get("voice_duration") or data.get("duration")
            data["voiceDuration"] = voice_dur

            # Resolve replyToMessageId / reply_to_message_id / replyToId / reply_to_id / parentMessageId
            reply_id = (
                data.get("replyToMessageId")
                or data.get("reply_to_message_id")
                or data.get("replyToId")
                or data.get("reply_to_id")
                or data.get("parentMessageId")
                or data.get("parent_message_id")
            )
            if reply_id and str(reply_id).strip() not in ("null", "undefined", ""):
                data["replyToMessageId"] = reply_id
            else:
                data["replyToMessageId"] = None

            # Resolve attachments list
            raw_att = data.get("attachments")
            if raw_att is None:
                data["attachments"] = []
        return data

    @model_validator(mode="after")
    def validate_content_presence(self) -> SendMessageRequest:
        has_text = bool(self.text and self.text.strip())
        has_att = bool(self.attachments and len(self.attachments) > 0)
        has_voice = bool(self.voiceUrl and self.voiceUrl.strip())
        if not has_text and not has_att and not has_voice:
            raise ValueError("Message must contain text, an attachment, or a voice message.")
        return self


class MessageReactionRequest(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def normalize_reaction(cls, data: Any) -> Any:
        if isinstance(data, dict):
            emoji_val = data.get("emoji") or data.get("reaction") or data.get("emoji_name") or data.get("reactionType")
            if emoji_val:
                data["emoji"] = emoji_val
        return data


class MessagePinRequest(BaseModel):
    isPinned: bool = True

    @model_validator(mode="before")
    @classmethod
    def normalize_pin(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "isPinned" in data:
                return data
            if "is_pinned" in data:
                data["isPinned"] = bool(data["is_pinned"])
            elif "pinned" in data:
                data["isPinned"] = bool(data["pinned"])
            else:
                data["isPinned"] = True
        return data


class ThreadReplyRequest(BaseModel):
    text: str | None = None
    attachments: list[AttachmentInput] = []
    voiceUrl: str | None = None
    voiceDuration: int | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_thread_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            text_val = data.get("text")
            if text_val is None:
                text_val = data.get("content") or data.get("message") or data.get("body")
            data["text"] = text_val

            voice_url = data.get("voiceUrl") or data.get("voice_url") or data.get("audioUrl") or data.get("audio_url")
            data["voiceUrl"] = voice_url

            voice_dur = data.get("voiceDuration") or data.get("voice_duration") or data.get("duration")
            data["voiceDuration"] = voice_dur

            raw_att = data.get("attachments")
            if raw_att is None:
                data["attachments"] = []
        return data

    @model_validator(mode="after")
    def validate_thread_content(self) -> ThreadReplyRequest:
        has_text = bool(self.text and self.text.strip())
        has_att = bool(self.attachments and len(self.attachments) > 0)
        has_voice = bool(self.voiceUrl and self.voiceUrl.strip())
        if not has_text and not has_att and not has_voice:
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

    @model_validator(mode="before")
    @classmethod
    def normalize_channel_create(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # isPrivate alias
            if "is_private" in data:
                data["isPrivate"] = bool(data["is_private"])
            elif "private" in data:
                data["isPrivate"] = bool(data["private"])

            # memberIds alias
            members = (
                data.get("memberIds")
                if "memberIds" in data
                else (data.get("member_ids") or data.get("members") or data.get("participantIds") or data.get("participants"))
            )
            if members is not None:
                data["memberIds"] = members
            else:
                data["memberIds"] = []
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_archive(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "is_archived" in data:
                data["isArchived"] = bool(data["is_archived"])
            elif "archived" in data:
                data["isArchived"] = bool(data["archived"])
            elif "isArchived" not in data:
                data["isArchived"] = True
        return data


# ===========================================================================
# D. Calls & WebRTC Schemas
# ===========================================================================

class CallInitiateRequest(BaseModel):
    targetUserId: uuid.UUID
    type: Literal["audio", "video"] = "audio"

    @model_validator(mode="before")
    @classmethod
    def normalize_call_initiate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            target_id = (
                data.get("targetUserId")
                or data.get("target_user_id")
                or data.get("recipientId")
                or data.get("recipient_id")
                or data.get("callee_id")
                or data.get("calleeId")
                or data.get("userId")
                or data.get("user_id")
            )
            if target_id is not None:
                data["targetUserId"] = target_id

            call_type = (data.get("type") or data.get("call_type") or data.get("callType") or "audio").lower()
            if call_type in ("audio", "video"):
                data["type"] = call_type
            else:
                data["type"] = "audio"
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_status(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_status = str(data.get("status", "")).lower().strip()
            # Map aliases
            status_map = {
                "accepted": "connected",
                "declined": "rejected",
                "busy": "rejected",
                "cancelled": "ended",
                "canceled": "ended",
            }
            mapped = status_map.get(raw_status, raw_status)
            if mapped in ("connected", "rejected", "ended", "missed", "failed"):
                data["status"] = mapped
        return data


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
    payload: dict[str, Any] = {}
    targetUserId: uuid.UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_signal(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_type = str(data.get("type") or data.get("signal_type") or data.get("signalType") or "").lower().strip()
            if raw_type in ("candidate", "ice_candidate"):
                raw_type = "ice-candidate"
            data["type"] = raw_type

            target_id = data.get("targetUserId") or data.get("target_user_id") or data.get("recipientId") or data.get("recipient_id")
            if target_id and str(target_id).strip() not in ("null", "undefined", ""):
                data["targetUserId"] = target_id
            else:
                data["targetUserId"] = None

            if "payload" not in data or data["payload"] is None:
                data["payload"] = {}
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_meeting_create(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # type
            m_type = str(data.get("type") or data.get("meeting_type") or "instant").lower().strip()
            data["type"] = "scheduled" if m_type == "scheduled" else "instant"

            # startTime
            start = data.get("startTime") or data.get("start_time")
            data["startTime"] = start

            # duration
            dur = data.get("duration") or data.get("duration_minutes") or data.get("durationMinutes") or 30
            try:
                data["duration"] = int(dur)
            except (ValueError, TypeError):
                data["duration"] = 30

            # participantIds
            p_ids = (
                data.get("participantIds")
                if "participantIds" in data
                else (data.get("participant_ids") or data.get("participants") or data.get("members"))
            )
            data["participantIds"] = p_ids if p_ids is not None else []

            # bool options
            if "allow_screen_share" in data:
                data["allowScreenShare"] = bool(data["allow_screen_share"])
            if "allow_microphone" in data:
                data["allowMicrophone"] = bool(data["allow_microphone"])
            if "allow_camera" in data:
                data["allowCamera"] = bool(data["allow_camera"])
            if "is_private" in data:
                data["isPrivate"] = bool(data["is_private"])
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_leave(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "end_for_everyone" in data:
                data["endForEveryone"] = bool(data["end_for_everyone"])
        return data


class MeetingMessageCreateRequest(BaseModel):
    message: str = Field(..., min_length=1)
    type: str = "chat"

    @model_validator(mode="before")
    @classmethod
    def normalize_message(cls, data: Any) -> Any:
        if isinstance(data, dict):
            msg = data.get("message") or data.get("content") or data.get("text") or data.get("body")
            if msg:
                data["message"] = str(msg)
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_presence(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_status = str(data.get("status", "online")).lower().strip()
            # Map aliases
            if raw_status in ("available", "active"):
                raw_status = "online"
            if raw_status in ("online", "away", "busy", "dnd", "offline"):
                data["status"] = raw_status
            else:
                data["status"] = "online"

            custom_st = (
                data.get("customStatus")
                if "customStatus" in data
                else (data.get("custom_status") or data.get("status_message") or data.get("message"))
            )
            data["customStatus"] = custom_st
        return data


class PresenceItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    status: str
    custom_status: str | None = None
    last_seen_at: datetime
    updated_at: datetime


class PresenceBatchRequest(BaseModel):
    userIds: list[uuid.UUID] = []

    @model_validator(mode="before")
    @classmethod
    def normalize_batch(cls, data: Any) -> Any:
        if isinstance(data, dict):
            u_ids = (
                data.get("userIds")
                if "userIds" in data
                else (data.get("user_ids") or data.get("users") or data.get("ids"))
            )
            data["userIds"] = u_ids if u_ids is not None else []
        elif isinstance(data, list):
            data = {"userIds": data}
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_sound_settings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize snake_case keys to camelCase
            mapping = {
                "master_volume": "masterVolume",
                "is_muted": "isMuted",
                "incoming_call_chime": "incomingCallChime",
                "outgoing_call_chime": "outgoingCallChime",
                "message_chime": "messageChime",
                "mention_chime": "mentionChime",
                "meeting_chime": "meetingChime",
                "notification_tone": "notificationTone",
            }
            normalized = dict(data)
            for snake, camel in mapping.items():
                if snake in normalized and camel not in normalized:
                    normalized[camel] = normalized[snake]
            return normalized
        return data


# ===========================================================================
# J. AI Copilot Schemas
# ===========================================================================

class AITransformRequest(BaseModel):
    text: str = Field(..., min_length=1)
    action: Literal["professional", "generate_reply", "tone", "shorten", "expand", "summarize"]
    tone: Literal["friendly", "diplomatic", "urgent"] | None = None
    context: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_ai_request(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # text
            text_val = data.get("text") or data.get("content") or data.get("prompt") or data.get("message") or data.get("input_text")
            if text_val:
                data["text"] = str(text_val)

            # action
            raw_action = str(data.get("action") or data.get("mode") or "professional").lower().strip()
            action_map = {
                "reply": "generate_reply",
                "formal": "professional",
                "rephrase": "professional",
                "summary": "summarize",
            }
            mapped_action = action_map.get(raw_action, raw_action)
            if mapped_action in ("professional", "generate_reply", "tone", "shorten", "expand", "summarize"):
                data["action"] = mapped_action
            else:
                data["action"] = "professional"

            # tone
            if "tone" in data and data["tone"]:
                raw_tone = str(data["tone"]).lower().strip()
                if raw_tone in ("friendly", "diplomatic", "urgent"):
                    data["tone"] = raw_tone
                else:
                    data["tone"] = None
        return data


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

    @model_validator(mode="before")
    @classmethod
    def normalize_mail_att(cls, data: Any) -> Any:
        if isinstance(data, dict):
            file_name = data.get("fileName") or data.get("file_name") or data.get("name") or "attachment"
            file_url = data.get("fileUrl") or data.get("file_url") or data.get("url") or ""
            file_type = data.get("fileType") or data.get("file_type") or data.get("type")
            return {
                "fileName": str(file_name),
                "fileUrl": str(file_url),
                "fileType": str(file_type) if file_type else None,
            }
        return data


class MailDispatchRequest(BaseModel):
    to: list[EmailStr] = Field(..., min_length=1)
    cc: list[EmailStr] | None = None
    bcc: list[EmailStr] | None = None
    subject: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    attachments: list[MailAttachmentInput] | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_mail_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # to
            to_val = data.get("to") or data.get("recipients") or data.get("recipient_emails")
            if isinstance(to_val, str):
                to_val = [e.strip() for e in to_val.split(",") if e.strip()]
            data["to"] = to_val if to_val else []

            # cc
            cc_val = data.get("cc")
            if isinstance(cc_val, str):
                data["cc"] = [e.strip() for e in cc_val.split(",") if e.strip()]

            # bcc
            bcc_val = data.get("bcc")
            if isinstance(bcc_val, str):
                data["bcc"] = [e.strip() for e in bcc_val.split(",") if e.strip()]

            # body
            body_val = data.get("body") or data.get("content") or data.get("message") or data.get("html")
            if body_val:
                data["body"] = str(body_val)
        return data


class MailDispatchResponse(BaseModel):
    dispatched: bool
    recipient_count: int
    message: str
