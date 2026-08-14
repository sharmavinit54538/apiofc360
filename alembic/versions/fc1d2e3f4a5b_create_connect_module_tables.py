"""create connect module tables

Revision ID: fc1d2e3f4a5b
Revises: fb1c2d3e4f5a
Create Date: 2026-08-14 15:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fc1d2e3f4a5b'
down_revision: Union[str, None] = 'fb1c2d3e4f5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. connect_conversations
    op.create_table(
        'connect_conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_message_preview', sa.String(500), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_conversations_company_id', 'connect_conversations', ['company_id'])
    op.create_index('ix_connect_conversations_last_message_at', 'connect_conversations', ['last_message_at'])
    op.create_index('ix_connect_conversations_is_deleted', 'connect_conversations', ['is_deleted'])

    # 2. connect_conversation_participants
    op.create_table(
        'connect_conversation_participants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_muted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.UniqueConstraint('conversation_id', 'user_id', name='uq_connect_conversation_participant'),
    )
    op.create_index('ix_connect_conv_participants_conv_id', 'connect_conversation_participants', ['conversation_id'])
    op.create_index('ix_connect_conv_participants_user_id', 'connect_conversation_participants', ['user_id'])
    op.create_index('ix_connect_conv_participants_company_id', 'connect_conversation_participants', ['company_id'])

    # 3. connect_channels
    op.create_table(
        'connect_channels',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_channels_company_id', 'connect_channels', ['company_id'])
    op.create_index('ix_connect_channels_name', 'connect_channels', ['name'])
    op.create_index('ix_connect_channels_is_archived', 'connect_channels', ['is_archived'])
    op.create_index('ix_connect_channels_is_deleted', 'connect_channels', ['is_deleted'])

    # 4. connect_channel_members
    op.create_table(
        'connect_channel_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('channel_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default=sa.text("'member'")),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_muted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.UniqueConstraint('channel_id', 'user_id', name='uq_connect_channel_member'),
    )
    op.create_index('ix_connect_channel_members_channel_id', 'connect_channel_members', ['channel_id'])
    op.create_index('ix_connect_channel_members_user_id', 'connect_channel_members', ['user_id'])
    op.create_index('ix_connect_channel_members_company_id', 'connect_channel_members', ['company_id'])

    # 5. connect_messages
    op.create_table(
        'connect_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_conversations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('channel_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_channels.id', ondelete='CASCADE'), nullable=True),
        sa.Column('sender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reply_to_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_messages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('parent_message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_messages.id', ondelete='CASCADE'), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('voice_url', sa.String(500), nullable=True),
        sa.Column('voice_duration', sa.Integer(), nullable=True),
        sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pinned_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_messages_company_id', 'connect_messages', ['company_id'])
    op.create_index('ix_connect_messages_conversation_id', 'connect_messages', ['conversation_id'])
    op.create_index('ix_connect_messages_channel_id', 'connect_messages', ['channel_id'])
    op.create_index('ix_connect_messages_sender_id', 'connect_messages', ['sender_id'])
    op.create_index('ix_connect_messages_parent_message_id', 'connect_messages', ['parent_message_id'])
    op.create_index('ix_connect_messages_created_at', 'connect_messages', ['created_at'])
    op.create_index('ix_connect_messages_is_deleted', 'connect_messages', ['is_deleted'])
    op.create_index('ix_connect_messages_is_pinned', 'connect_messages', ['is_pinned'])

    # 6. connect_message_reactions
    op.create_table(
        'connect_message_reactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('emoji', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('message_id', 'user_id', 'emoji', name='uq_connect_msg_user_emoji'),
    )
    op.create_index('ix_connect_msg_reactions_msg_id', 'connect_message_reactions', ['message_id'])
    op.create_index('ix_connect_msg_reactions_user_id', 'connect_message_reactions', ['user_id'])
    op.create_index('ix_connect_msg_reactions_company_id', 'connect_message_reactions', ['company_id'])

    # 7. connect_message_attachments
    op.create_table(
        'connect_message_attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(100), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_msg_attachments_msg_id', 'connect_message_attachments', ['message_id'])
    op.create_index('ix_connect_msg_attachments_company_id', 'connect_message_attachments', ['company_id'])

    # 8. connect_call_logs
    op.create_table(
        'connect_call_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('caller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('callee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('call_type', sa.String(20), nullable=False, server_default=sa.text("'audio'")),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'initiated'")),
        sa.Column('room_id', sa.String(100), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_call_logs_company_id', 'connect_call_logs', ['company_id'])
    op.create_index('ix_connect_call_logs_caller_id', 'connect_call_logs', ['caller_id'])
    op.create_index('ix_connect_call_logs_callee_id', 'connect_call_logs', ['callee_id'])
    op.create_index('ix_connect_call_logs_status', 'connect_call_logs', ['status'])
    op.create_index('ix_connect_call_logs_created_at', 'connect_call_logs', ['created_at'])

    # 9. connect_meetings
    op.create_table(
        'connect_meetings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('host_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('meeting_code', sa.String(50), nullable=False),
        sa.Column('meeting_type', sa.String(20), nullable=False, server_default=sa.text("'instant'")),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'scheduled'")),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default=sa.text('30')),
        sa.Column('allow_screen_share', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('allow_microphone', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('allow_camera', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_private', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_meetings_company_id', 'connect_meetings', ['company_id'])
    op.create_index('ix_connect_meetings_host_id', 'connect_meetings', ['host_id'])
    op.create_index('ix_connect_meetings_meeting_code', 'connect_meetings', ['meeting_code'], unique=True)
    op.create_index('ix_connect_meetings_status', 'connect_meetings', ['status'])
    op.create_index('ix_connect_meetings_start_time', 'connect_meetings', ['start_time'])

    # 10. connect_meeting_participants
    op.create_table(
        'connect_meeting_participants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('meeting_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default=sa.text("'participant'")),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'invited'")),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('meeting_id', 'user_id', name='uq_connect_meeting_user'),
    )
    op.create_index('ix_connect_meeting_part_meeting_id', 'connect_meeting_participants', ['meeting_id'])
    op.create_index('ix_connect_meeting_part_user_id', 'connect_meeting_participants', ['user_id'])
    op.create_index('ix_connect_meeting_part_company_id', 'connect_meeting_participants', ['company_id'])

    # 11. connect_meeting_messages
    op.create_table(
        'connect_meeting_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('meeting_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('connect_meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_meeting_msg_meeting_id', 'connect_meeting_messages', ['meeting_id'])
    op.create_index('ix_connect_meeting_msg_sender_id', 'connect_meeting_messages', ['sender_id'])
    op.create_index('ix_connect_meeting_msg_company_id', 'connect_meeting_messages', ['company_id'])
    op.create_index('ix_connect_meeting_msg_created_at', 'connect_meeting_messages', ['created_at'])

    # 12. connect_shared_files
    op.create_table(
        'connect_shared_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uploader_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(100), nullable=False),
        sa.Column('file_category', sa.String(50), nullable=False, server_default=sa.text("'documents'")),
        sa.Column('file_size', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_shared_files_company_id', 'connect_shared_files', ['company_id'])
    op.create_index('ix_connect_shared_files_uploader_id', 'connect_shared_files', ['uploader_id'])
    op.create_index('ix_connect_shared_files_file_category', 'connect_shared_files', ['file_category'])
    op.create_index('ix_connect_shared_files_is_deleted', 'connect_shared_files', ['is_deleted'])
    op.create_index('ix_connect_shared_files_created_at', 'connect_shared_files', ['created_at'])

    # 13. connect_user_presence
    op.create_table(
        'connect_user_presence',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'offline'")),
        sa.Column('custom_status', sa.String(255), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', name='uq_connect_presence_user'),
    )
    op.create_index('ix_connect_user_presence_company_id', 'connect_user_presence', ['company_id'])
    op.create_index('ix_connect_user_presence_status', 'connect_user_presence', ['status'])

    # 14. connect_notifications
    op.create_table(
        'connect_notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recipient_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sender_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('resource_id', sa.String(100), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_connect_notif_recipient_id', 'connect_notifications', ['recipient_id'])
    op.create_index('ix_connect_notif_company_id', 'connect_notifications', ['company_id'])
    op.create_index('ix_connect_notif_is_read', 'connect_notifications', ['is_read'])
    op.create_index('ix_connect_notif_type', 'connect_notifications', ['notification_type'])
    op.create_index('ix_connect_notif_created_at', 'connect_notifications', ['created_at'])

    # 15. connect_user_sound_settings
    op.create_table(
        'connect_user_sound_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('master_volume', sa.Integer(), nullable=False, server_default=sa.text('80')),
        sa.Column('is_muted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('incoming_call_chime', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('outgoing_call_chime', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('message_chime', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('mention_chime', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('meeting_chime', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('ringtone', sa.String(100), nullable=False, server_default=sa.text("'aurix_default_ringtone.mp3'")),
        sa.Column('notification_tone', sa.String(100), nullable=False, server_default=sa.text("'aurix_default_notification.mp3'")),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', name='uq_connect_sound_user'),
    )
    op.create_index('ix_connect_sound_user_id', 'connect_user_sound_settings', ['user_id'])
    op.create_index('ix_connect_sound_company_id', 'connect_user_sound_settings', ['company_id'])


def downgrade() -> None:
    op.drop_table('connect_user_sound_settings')
    op.drop_table('connect_notifications')
    op.drop_table('connect_user_presence')
    op.drop_table('connect_shared_files')
    op.drop_table('connect_meeting_messages')
    op.drop_table('connect_meeting_participants')
    op.drop_table('connect_meetings')
    op.drop_table('connect_call_logs')
    op.drop_table('connect_message_attachments')
    op.drop_table('connect_message_reactions')
    op.drop_table('connect_messages')
    op.drop_table('connect_channel_members')
    op.drop_table('connect_channels')
    op.drop_table('connect_conversation_participants')
    op.drop_table('connect_conversations')
