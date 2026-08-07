"""Add leave_request tables

Revision ID: 426a11878947
Revises: 604773312516
Create Date: 2026-07-07 23:14:07.835211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '426a11878947'
down_revision: Union[str, None] = '604773312516'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'leave_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('leave_type', sa.String(length=50), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('total_days', sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='PENDING', nullable=False),
        sa.Column('approved_by_id', sa.UUID(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_leave_requests_dates', 'leave_requests', ['start_date', 'end_date'], unique=False)
    op.create_index('ix_leave_requests_employee_id', 'leave_requests', ['employee_id'], unique=False)
    op.create_index('ix_leave_requests_status', 'leave_requests', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_leave_requests_status', table_name='leave_requests')
    op.drop_index('ix_leave_requests_employee_id', table_name='leave_requests')
    op.drop_index('ix_leave_requests_dates', table_name='leave_requests')
    op.drop_table('leave_requests')
