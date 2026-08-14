"""OFC360 Connect database models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class ConnectConversation(Base):
    """Direct message conversations between company colleagues."""

    __tablename__ = "connect_conversations"
    __table_args__ = (
        Index("ix_connect_conversations_company_id", "company_id"),
        Index("ix_connect_conversations_last_message_at", "last_message_at"),
        Index("ix_connect_conversations_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by], lazy="select")
    participants: Mapped[list[ConnectConversationParticipant]] = relationship(
        "ConnectConversationParticipant",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    messages: Mapped[list[ConnectMessage]] = relationship(
        "ConnectMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ConnectConversationParticipant(Base):
    """Participants inside a direct messaging conversation."""

    __tablename__ = "connect_conversation_participants"
    __table_args__ = (
        Index("ix_connect_conv_participants_conv_id", "conversation_id"),
        Index("ix_connect_conv_participants_user_id", "user_id"),
        Index("ix_connect_conv_participants_company_id", "company_id"),
        UniqueConstraint("conversation_id", "user_id", name="uq_connect_conversation_participant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_conversations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    # Relations
    conversation: Mapped[ConnectConversation] = relationship("ConnectConversation", back_populates="participants")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")


class ConnectChannel(Base):
    """Team channels for group communication."""

    __tablename__ = "connect_channels"
    __table_args__ = (
        Index("ix_connect_channels_company_id", "company_id"),
        Index("ix_connect_channels_name", "name"),
        Index("ix_connect_channels_is_archived", "is_archived"),
        Index("ix_connect_channels_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    creator: Mapped[User] = relationship("User", foreign_keys=[created_by], lazy="selectin")
    members: Mapped[list[ConnectChannelMember]] = relationship(
        "ConnectChannelMember",
        back_populates="channel",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    messages: Mapped[list[ConnectMessage]] = relationship(
        "ConnectMessage",
        back_populates="channel",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ConnectChannelMember(Base):
    """Membership of users in team channels."""

    __tablename__ = "connect_channel_members"
    __table_args__ = (
        Index("ix_connect_channel_members_channel_id", "channel_id"),
        Index("ix_connect_channel_members_user_id", "user_id"),
        Index("ix_connect_channel_members_company_id", "company_id"),
        UniqueConstraint("channel_id", "user_id", name="uq_connect_channel_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_channels.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member", server_default=text("'member'"))  # host, admin, member
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    # Relations
    channel: Mapped[ConnectChannel] = relationship("ConnectChannel", back_populates="members")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")


class ConnectMessage(Base):
    """Messages sent in conversations, channels, or threads."""

    __tablename__ = "connect_messages"
    __table_args__ = (
        Index("ix_connect_messages_company_id", "company_id"),
        Index("ix_connect_messages_conversation_id", "conversation_id"),
        Index("ix_connect_messages_channel_id", "channel_id"),
        Index("ix_connect_messages_sender_id", "sender_id"),
        Index("ix_connect_messages_parent_message_id", "parent_message_id"),
        Index("ix_connect_messages_created_at", "created_at"),
        Index("ix_connect_messages_is_deleted", "is_deleted"),
        Index("ix_connect_messages_is_pinned", "is_pinned"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_conversations.id", ondelete="CASCADE"), nullable=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_channels.id", ondelete="CASCADE"), nullable=True)
    sender_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_messages.id", ondelete="SET NULL"), nullable=True)
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_messages.id", ondelete="CASCADE"), nullable=True)

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    voice_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # duration in seconds

    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pinned_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    conversation: Mapped[ConnectConversation | None] = relationship("ConnectConversation", back_populates="messages")
    channel: Mapped[ConnectChannel | None] = relationship("ConnectChannel", back_populates="messages")
    sender: Mapped[User] = relationship("User", foreign_keys=[sender_id], lazy="selectin")
    reply_to: Mapped[ConnectMessage | None] = relationship("ConnectMessage", foreign_keys=[reply_to_id], remote_side=[id], lazy="select")
    pinned_by_user: Mapped[User | None] = relationship("User", foreign_keys=[pinned_by], lazy="select")

    reactions: Mapped[list[ConnectMessageReaction]] = relationship(
        "ConnectMessageReaction",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attachments: Mapped[list[ConnectMessageAttachment]] = relationship(
        "ConnectMessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    thread_replies: Mapped[list[ConnectMessage]] = relationship(
        "ConnectMessage",
        foreign_keys=[parent_message_id],
        backref="parent_message",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ConnectMessageReaction(Base):
    """Emoji reactions on messages."""

    __tablename__ = "connect_message_reactions"
    __table_args__ = (
        Index("ix_connect_msg_reactions_msg_id", "message_id"),
        Index("ix_connect_msg_reactions_user_id", "user_id"),
        Index("ix_connect_msg_reactions_company_id", "company_id"),
        UniqueConstraint("message_id", "user_id", "emoji", name="uq_connect_msg_user_emoji"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_messages.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    emoji: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    message: Mapped[ConnectMessage] = relationship("ConnectMessage", back_populates="reactions")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")


class ConnectMessageAttachment(Base):
    """File attachments on messages."""

    __tablename__ = "connect_message_attachments"
    __table_args__ = (
        Index("ix_connect_msg_attachments_msg_id", "message_id"),
        Index("ix_connect_msg_attachments_company_id", "company_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_messages.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    message: Mapped[ConnectMessage] = relationship("ConnectMessage", back_populates="attachments")


class ConnectCallLog(Base):
    """Audio and video call session history records."""

    __tablename__ = "connect_call_logs"
    __table_args__ = (
        Index("ix_connect_call_logs_company_id", "company_id"),
        Index("ix_connect_call_logs_caller_id", "caller_id"),
        Index("ix_connect_call_logs_callee_id", "callee_id"),
        Index("ix_connect_call_logs_status", "status"),
        Index("ix_connect_call_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    caller_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    callee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    call_type: Mapped[str] = mapped_column(String(20), nullable=False, default="audio")  # audio, video
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="initiated")  # initiated, ringing, connected, rejected, ended, missed, failed
    room_id: Mapped[str] = mapped_column(String(100), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    caller: Mapped[User] = relationship("User", foreign_keys=[caller_id], lazy="selectin")
    callee: Mapped[User] = relationship("User", foreign_keys=[callee_id], lazy="selectin")


class ConnectMeeting(Base):
    """Instant and scheduled video meetings."""

    __tablename__ = "connect_meetings"
    __table_args__ = (
        Index("ix_connect_meetings_company_id", "company_id"),
        Index("ix_connect_meetings_host_id", "host_id"),
        Index("ix_connect_meetings_meeting_code", "meeting_code", unique=True),
        Index("ix_connect_meetings_status", "status"),
        Index("ix_connect_meetings_start_time", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    host_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_code: Mapped[str] = mapped_column(String(50), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(20), nullable=False, default="instant")  # instant, scheduled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", server_default=text("'scheduled'"))  # scheduled, live, ended, cancelled

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    allow_screen_share: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_microphone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_camera: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    host: Mapped[User] = relationship("User", foreign_keys=[host_id], lazy="selectin")
    participants: Mapped[list[ConnectMeetingParticipant]] = relationship(
        "ConnectMeetingParticipant",
        back_populates="meeting",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    chat_messages: Mapped[list[ConnectMeetingMessage]] = relationship(
        "ConnectMeetingMessage",
        back_populates="meeting",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ConnectMeetingParticipant(Base):
    """Participants registered or active in a video meeting."""

    __tablename__ = "connect_meeting_participants"
    __table_args__ = (
        Index("ix_connect_meeting_part_meeting_id", "meeting_id"),
        Index("ix_connect_meeting_part_user_id", "user_id"),
        Index("ix_connect_meeting_part_company_id", "company_id"),
        UniqueConstraint("meeting_id", "user_id", name="uq_connect_meeting_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_meetings.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    role: Mapped[str] = mapped_column(String(20), nullable=False, default="participant", server_default=text("'participant'"))  # host, co-host, participant
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited", server_default=text("'invited'"))  # invited, joined, left, declined
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    meeting: Mapped[ConnectMeeting] = relationship("ConnectMeeting", back_populates="participants")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")


class ConnectMeetingMessage(Base):
    """In-meeting real-time chat messages."""

    __tablename__ = "connect_meeting_messages"
    __table_args__ = (
        Index("ix_connect_meeting_msg_meeting_id", "meeting_id"),
        Index("ix_connect_meeting_msg_sender_id", "sender_id"),
        Index("ix_connect_meeting_msg_company_id", "company_id"),
        Index("ix_connect_meeting_msg_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("connect_meetings.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    meeting: Mapped[ConnectMeeting] = relationship("ConnectMeeting", back_populates="chat_messages")
    sender: Mapped[User] = relationship("User", foreign_keys=[sender_id], lazy="selectin")


class ConnectSharedFile(Base):
    """Files shared directly or uploaded via Connect."""

    __tablename__ = "connect_shared_files"
    __table_args__ = (
        Index("ix_connect_shared_files_company_id", "company_id"),
        Index("ix_connect_shared_files_uploader_id", "uploader_id"),
        Index("ix_connect_shared_files_file_category", "file_category"),
        Index("ix_connect_shared_files_is_deleted", "is_deleted"),
        Index("ix_connect_shared_files_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    uploader_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_category: Mapped[str] = mapped_column(String(50), nullable=False, default="documents")  # images, videos, documents, spreadsheets, other
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    uploader: Mapped[User] = relationship("User", foreign_keys=[uploader_id], lazy="selectin")


class ConnectUserPresence(Base):
    """Real-time presence and status indicators."""

    __tablename__ = "connect_user_presence"
    __table_args__ = (
        Index("ix_connect_user_presence_company_id", "company_id"),
        Index("ix_connect_user_presence_status", "status"),
        UniqueConstraint("user_id", name="uq_connect_presence_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="offline", server_default=text("'offline'"))  # online, away, busy, dnd, offline
    custom_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")


class ConnectNotification(Base):
    """Notifications dispatched for Connect events."""

    __tablename__ = "connect_notifications"
    __table_args__ = (
        Index("ix_connect_notif_recipient_id", "recipient_id"),
        Index("ix_connect_notif_company_id", "company_id"),
        Index("ix_connect_notif_is_read", "is_read"),
        Index("ix_connect_notif_type", "notification_type"),
        Index("ix_connect_notif_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)  # message, mention, call, meeting, file, channel
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    recipient: Mapped[User] = relationship("User", foreign_keys=[recipient_id], lazy="selectin")
    sender: Mapped[User | None] = relationship("User", foreign_keys=[sender_id], lazy="selectin")


class ConnectUserSoundSettings(Base):
    """User audio feedback and chime preferences."""

    __tablename__ = "connect_user_sound_settings"
    __table_args__ = (
        Index("ix_connect_sound_user_id", "user_id"),
        Index("ix_connect_sound_company_id", "company_id"),
        UniqueConstraint("user_id", name="uq_connect_sound_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    master_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=80, server_default=text("80"))
    is_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    incoming_call_chime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    outgoing_call_chime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    message_chime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    mention_chime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    meeting_chime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    ringtone: Mapped[str] = mapped_column(String(100), nullable=False, default="aurix_default_ringtone.mp3", server_default=text("'aurix_default_ringtone.mp3'"))
    notification_tone: Mapped[str] = mapped_column(String(100), nullable=False, default="aurix_default_notification.mp3", server_default=text("'aurix_default_notification.mp3'"))

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relations
    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")
