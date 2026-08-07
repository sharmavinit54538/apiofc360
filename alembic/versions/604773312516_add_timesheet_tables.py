"""Add timesheet tables

Revision ID: 604773312516
Revises: f1a2b3c4d5e6
Create Date: 2026-07-07 22:54:34.592200

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '604773312516'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create timesheets table
    op.create_table(
        'timesheets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('week_start_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='DRAFT', nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_id', sa.UUID(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_timesheets_employee_id', 'timesheets', ['employee_id'], unique=False)
    op.create_index('ix_timesheets_status', 'timesheets', ['status'], unique=False)
    op.create_index('ix_timesheets_week_start_date', 'timesheets', ['week_start_date'], unique=False)

    # 2. Create timesheet_entries table
    op.create_table(
        'timesheet_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('timesheet_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.String(length=100), nullable=False),
        sa.Column('monday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('tuesday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('wednesday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('thursday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('friday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('saturday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('sunday_hours', sa.Numeric(precision=4, scale=2), server_default='0.00', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['timesheet_id'], ['timesheets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_timesheet_entries_timesheet_id', 'timesheet_entries', ['timesheet_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_timesheet_entries_timesheet_id', table_name='timesheet_entries')
    op.drop_table('timesheet_entries')
    op.drop_index('ix_timesheets_week_start_date', table_name='timesheets')
    op.drop_index('ix_timesheets_status', table_name='timesheets')
    op.drop_index('ix_timesheets_employee_id', table_name='timesheets')
    op.drop_table('timesheets')
