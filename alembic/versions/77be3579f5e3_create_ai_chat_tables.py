"""create_ai_chat_tables

Revision ID: 77be3579f5e3
Revises: 624a163bf6a8
Create Date: 2026-07-03 12:56:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77be3579f5e3'
down_revision: Union[str, None] = '624a163bf6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ai_conversations table
    op.create_table(
        'ai_conversations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_ai_conversations_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_conversations_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_conversations'))
    )
    op.create_index('ix_ai_conversations_user_id', 'ai_conversations', ['user_id'], unique=False)
    op.create_index('ix_ai_conversations_company_id', 'ai_conversations', ['company_id'], unique=False)

    # Create ai_messages table
    op.create_table(
        'ai_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id'], name=op.f('fk_ai_messages_conversation_id_ai_conversations'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_messages'))
    )
    op.create_index('ix_ai_messages_conversation_id', 'ai_messages', ['conversation_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_messages_conversation_id', table_name='ai_messages')
    op.drop_table('ai_messages')
    op.drop_index('ix_ai_conversations_company_id', table_name='ai_conversations')
    op.drop_index('ix_ai_conversations_user_id', table_name='ai_conversations')
    op.drop_table('ai_conversations')
