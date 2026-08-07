"""Add Generated Goal tables

Revision ID: 3927aa4d676b
Revises: de18a5732ab3
Create Date: 2026-07-06 10:23:41.550253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3927aa4d676b'
down_revision: Union[str, None] = 'de18a5732ab3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create generated_goals table
    op.create_table(
        'generated_goals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=True),
        sa.Column('goal_type', sa.String(length=30), nullable=False),
        sa.Column('scope', sa.String(length=30), server_default='INDIVIDUAL', nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_metric', sa.String(length=100), nullable=False),
        sa.Column('current_value', sa.String(length=100), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='ACTIVE', nullable=False),
        sa.Column('original_target', sa.String(length=100), nullable=True),
        sa.Column('adjustment_reason', sa.Text(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generated_goals_company_id', 'generated_goals', ['company_id'], unique=False)
    op.create_index('ix_generated_goals_employee_id', 'generated_goals', ['employee_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_generated_goals_employee_id', table_name='generated_goals')
    op.drop_index('ix_generated_goals_company_id', table_name='generated_goals')
    op.drop_table('generated_goals')
