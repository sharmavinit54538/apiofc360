"""Add AI Emotion Chatbot tables

Revision ID: c5b37379742c
Revises: 12f939d81c44
Create Date: 2026-07-06 10:34:03.930569

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5b37379742c'
down_revision: Union[str, None] = '12f939d81c44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create emotion_aware_chat_sessions table
    op.create_table(
        'emotion_aware_chat_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_emotion_chat_sessions_employee_id', 'emotion_aware_chat_sessions', ['employee_id'], unique=False)

    # 2. create emotion_aware_chat_messages table
    op.create_table(
        'emotion_aware_chat_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('sender_role', sa.String(length=20), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('detected_emotion', sa.String(length=30), server_default='NEUTRAL', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['emotion_aware_chat_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('emotion_aware_chat_messages')
    op.drop_index('ix_emotion_chat_sessions_employee_id', table_name='emotion_aware_chat_sessions')
    op.drop_table('emotion_aware_chat_sessions')
