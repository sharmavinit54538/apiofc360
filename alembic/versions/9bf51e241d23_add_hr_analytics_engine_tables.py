"""Add HR Analytics engine tables

Revision ID: 9bf51e241d23
Revises: 6e2c0af49612
Create Date: 2026-07-06 09:55:38.288527

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9bf51e241d23'
down_revision: Union[str, None] = '6e2c0af49612'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create hr_analytics_snapshots table
    op.create_table(
        'hr_analytics_snapshots',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), server_default=sa.text('CURRENT_DATE'), nullable=False),
        sa.Column('total_headcount', sa.Integer(), nullable=False),
        sa.Column('average_tenure_months', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('overall_attrition_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('diversity_metrics', sa.JSON(), nullable=True),
        sa.Column('salary_metrics', sa.JSON(), nullable=True),
        sa.Column('leave_attendance_metrics', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. create hr_attrition_predictions table
    op.create_table(
        'hr_attrition_predictions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('risk_score', sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column('risk_level', sa.String(length=20), nullable=False),
        sa.Column('top_risk_factors', sa.JSON(), nullable=True),
        sa.Column('retention_recommendations', sa.Text(), nullable=True),
        sa.Column('predicted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_hr_attrition_predictions_employee', 'hr_attrition_predictions', ['employee_id'], unique=False)
    op.create_index('ix_hr_attrition_predictions_level', 'hr_attrition_predictions', ['risk_level'], unique=False)

    # 3. create hr_forecasting_runs table
    op.create_table(
        'hr_forecasting_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('forecast_type', sa.String(length=50), nullable=False),
        sa.Column('forecast_target_date', sa.Date(), nullable=False),
        sa.Column('predicted_value', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('lower_confidence_bound', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('upper_confidence_bound', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('model_parameters', sa.JSON(), nullable=True),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('hr_forecasting_runs')
    op.drop_index('ix_hr_attrition_predictions_level', table_name='hr_attrition_predictions')
    op.drop_index('ix_hr_attrition_predictions_employee', table_name='hr_attrition_predictions')
    op.drop_table('hr_attrition_predictions')
    op.drop_table('hr_analytics_snapshots')
