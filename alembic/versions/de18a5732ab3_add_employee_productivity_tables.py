"""Add Employee Productivity tables

Revision ID: de18a5732ab3
Revises: 9a0b3f7464e6
Create Date: 2026-07-06 10:20:20.481202

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de18a5732ab3'
down_revision: Union[str, None] = '9a0b3f7464e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create employee_productivity_logs table
    op.create_table(
        'employee_productivity_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('focus_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('deep_work_hours', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('idle_hours', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('meeting_hours', sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column('tasks_completed_count', sa.Integer(), nullable=False),
        sa.Column('recorded_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_productivity_logs_employee_id', 'employee_productivity_logs', ['employee_id'], unique=False)

    # 2. create productivity_forecasting_runs table
    op.create_table(
        'productivity_forecasting_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('predicted_focus_score', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('predicted_burnout_risk', sa.String(length=20), nullable=False),
        sa.Column('ai_recommendations', sa.Text(), nullable=False),
        sa.Column('forecasted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_productivity_forecasts_employee_id', 'productivity_forecasting_runs', ['employee_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_productivity_forecasts_employee_id', table_name='productivity_forecasting_runs')
    op.drop_table('productivity_forecasting_runs')
    op.drop_index('ix_productivity_logs_employee_id', table_name='employee_productivity_logs')
    op.drop_table('employee_productivity_logs')
