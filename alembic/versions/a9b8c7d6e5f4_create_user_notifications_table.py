"""create user_notifications table

Revision ID: a9b8c7d6e5f4
Revises: 696aaf0392de
Create Date: 2026-10-01 08:21:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = '696aaf0392de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recipient_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('module', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default=sa.text("'normal'")),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.String(length=1000), nullable=False),
        sa.Column('link', sa.String(length=500), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=True),
        sa.Column('entity_id', sa.String(length=100), nullable=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index('ix_user_notifications_company_id', 'user_notifications', ['company_id'], unique=False)
    op.create_index('ix_user_notifications_recipient_id', 'user_notifications', ['recipient_id'], unique=False)
    op.create_index(
        'ix_user_notifications_recipient_read_created',
        'user_notifications',
        ['recipient_id', 'read_at', sa.text('created_at DESC')],
        unique=False,
    )
    op.create_index(
        'uq_user_notifications_recipient_dedupe',
        'user_notifications',
        ['recipient_id', 'dedupe_key'],
        unique=True,
        postgresql_where=sa.text('dedupe_key IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_user_notifications_recipient_dedupe', table_name='user_notifications')
    op.drop_index('ix_user_notifications_recipient_read_created', table_name='user_notifications')
    op.drop_index('ix_user_notifications_recipient_id', table_name='user_notifications')
    op.drop_index('ix_user_notifications_company_id', table_name='user_notifications')
    op.drop_table('user_notifications')
