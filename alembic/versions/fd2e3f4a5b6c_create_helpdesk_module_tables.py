"""create helpdesk module tables

Revision ID: fd2e3f4a5b6c
Revises: fc1d2e3f4a5b
Create Date: 2026-08-14 16:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fd2e3f4a5b6c'
down_revision: Union[str, None] = 'fc1d2e3f4a5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. helpdesk_tickets
    op.create_table(
        'helpdesk_tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ticket_number', sa.String(length=50), nullable=False),
        sa.Column('requester_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assigned_to_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.String(length=20), server_default=sa.text("'Medium'"), nullable=False),
        sa.Column('status', sa.String(length=30), server_default=sa.text("'Open'"), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('sla_first_response_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sla_resolution_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('company_id', 'ticket_number', name='uq_helpdesk_ticket_company_number'),
    )
    op.create_index('ix_helpdesk_tickets_company_requester_created', 'helpdesk_tickets', ['company_id', 'requester_id', 'created_at'])
    op.create_index('ix_helpdesk_tickets_company_status', 'helpdesk_tickets', ['company_id', 'status'])
    op.create_index('ix_helpdesk_tickets_assigned_to', 'helpdesk_tickets', ['assigned_to_id'])
    op.create_index('ix_helpdesk_tickets_sla_resolution_due_at', 'helpdesk_tickets', ['sla_resolution_due_at'])
    op.create_index('ix_helpdesk_tickets_category', 'helpdesk_tickets', ['category'])
    op.create_index('ix_helpdesk_tickets_priority', 'helpdesk_tickets', ['priority'])

    # 2. helpdesk_comments
    op.create_table(
        'helpdesk_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('ticket_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('helpdesk_tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_helpdesk_comments_ticket_created', 'helpdesk_comments', ['ticket_id', 'created_at'])

    # 3. helpdesk_internal_notes
    op.create_table(
        'helpdesk_internal_notes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('ticket_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('helpdesk_tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_helpdesk_internal_notes_ticket_created', 'helpdesk_internal_notes', ['ticket_id', 'created_at'])

    # 4. helpdesk_attachments
    op.create_table(
        'helpdesk_attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ticket_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('helpdesk_tickets.id', ondelete='CASCADE'), nullable=True),
        sa.Column('comment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('helpdesk_comments.id', ondelete='CASCADE'), nullable=True),
        sa.Column('uploader_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('file_path', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_helpdesk_attachments_ticket_id', 'helpdesk_attachments', ['ticket_id'])
    op.create_index('ix_helpdesk_attachments_comment_id', 'helpdesk_attachments', ['comment_id'])
    op.create_index('ix_helpdesk_attachments_company_id', 'helpdesk_attachments', ['company_id'])

    # 5. helpdesk_faqs
    op.create_table(
        'helpdesk_faqs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('is_public', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('view_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_helpful_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_helpdesk_faqs_company_category', 'helpdesk_faqs', ['company_id', 'category'])
    op.create_index('ix_helpdesk_faqs_is_public', 'helpdesk_faqs', ['is_public'])


def downgrade() -> None:
    op.drop_index('ix_helpdesk_faqs_is_public', table_name='helpdesk_faqs')
    op.drop_index('ix_helpdesk_faqs_company_category', table_name='helpdesk_faqs')
    op.drop_table('helpdesk_faqs')

    op.drop_index('ix_helpdesk_attachments_company_id', table_name='helpdesk_attachments')
    op.drop_index('ix_helpdesk_attachments_comment_id', table_name='helpdesk_attachments')
    op.drop_index('ix_helpdesk_attachments_ticket_id', table_name='helpdesk_attachments')
    op.drop_table('helpdesk_attachments')

    op.drop_index('ix_helpdesk_internal_notes_ticket_created', table_name='helpdesk_internal_notes')
    op.drop_table('helpdesk_internal_notes')

    op.drop_index('ix_helpdesk_comments_ticket_created', table_name='helpdesk_comments')
    op.drop_table('helpdesk_comments')

    op.drop_index('ix_helpdesk_tickets_priority', table_name='helpdesk_tickets')
    op.drop_index('ix_helpdesk_tickets_category', table_name='helpdesk_tickets')
    op.drop_index('ix_helpdesk_tickets_sla_resolution_due_at', table_name='helpdesk_tickets')
    op.drop_index('ix_helpdesk_tickets_assigned_to', table_name='helpdesk_tickets')
    op.drop_index('ix_helpdesk_tickets_company_status', table_name='helpdesk_tickets')
    op.drop_index('ix_helpdesk_tickets_company_requester_created', table_name='helpdesk_tickets')
    op.drop_table('helpdesk_tickets')
