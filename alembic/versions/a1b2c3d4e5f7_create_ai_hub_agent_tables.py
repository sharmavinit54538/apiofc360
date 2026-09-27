"""create ai hub agent tables

Revision ID: a1b2c3d4e5f7
Revises: fe2c3d4e5f6b
Create Date: 2026-09-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'fe2c3d4e5f6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. create agent_runs table (idempotent – skip if already exists from partial prior run)
    if 'agent_runs' not in existing_tables:
        op.create_table(
            'agent_runs',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('company_id', sa.UUID(), nullable=True),
            sa.Column('agent_id', sa.String(length=100), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=True),
            sa.Column('trigger', sa.String(length=50), server_default='manual', nullable=False),
            sa.Column('prompt', sa.Text(), nullable=True),
            sa.Column('parameters', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True),
            sa.Column('context', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True),
            sa.Column('status', sa.String(length=50), server_default='RUNNING', nullable=False),
            sa.Column('result', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('agent_runs')} if 'agent_runs' in inspector.get_table_names() else set()
    if 'ix_agent_runs_company_id' not in existing_indexes:
        op.create_index('ix_agent_runs_company_id', 'agent_runs', ['company_id'], unique=False)
    if 'ix_agent_runs_agent_id' not in existing_indexes:
        op.create_index('ix_agent_runs_agent_id', 'agent_runs', ['agent_id'], unique=False)
    if 'ix_agent_runs_created_at' not in existing_indexes:
        op.create_index('ix_agent_runs_created_at', 'agent_runs', ['started_at'], unique=False)

    # 2. create agent_feedback table (idempotent)
    if 'agent_feedback' not in existing_tables:
        op.create_table(
            'agent_feedback',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('run_id', sa.UUID(), nullable=False),
            sa.Column('rating', sa.Integer(), nullable=False),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('tags', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True),
            sa.Column('created_by', sa.UUID(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )

    existing_fb_indexes = {idx['name'] for idx in inspector.get_indexes('agent_feedback')} if 'agent_feedback' in inspector.get_table_names() else set()
    if 'ix_agent_feedback_run_id' not in existing_fb_indexes:
        op.create_index('ix_agent_feedback_run_id', 'agent_feedback', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agent_feedback_run_id', table_name='agent_feedback')
    op.drop_table('agent_feedback')
    op.drop_index('ix_agent_runs_created_at', table_name='agent_runs')
    op.drop_index('ix_agent_runs_agent_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_company_id', table_name='agent_runs')
    op.drop_table('agent_runs')
