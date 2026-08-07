"""Add AI Compensation tables

Revision ID: 4ad46d158471
Revises: 3927aa4d676b
Create Date: 2026-07-06 10:26:32.040004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ad46d158471'
down_revision: Union[str, None] = '3927aa4d676b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create market_compensation_benchmarks table
    op.create_table(
        'market_compensation_benchmarks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('designation', sa.String(length=100), nullable=False),
        sa.Column('experience_years', sa.Integer(), nullable=False),
        sa.Column('market_min_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('market_median_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('market_max_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('region', sa.String(length=100), server_default='Global', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_benchmarks_designation_exp', 'market_compensation_benchmarks', ['designation', 'experience_years'], unique=False)

    # 2. create ai_compensation_recommendations table
    op.create_table(
        'ai_compensation_recommendations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('recommended_salary', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('recommended_bonus', sa.Numeric(precision=12, scale=2), server_default='0.00', nullable=False),
        sa.Column('recommended_incentives', sa.Numeric(precision=12, scale=2), server_default='0.00', nullable=False),
        sa.Column('recommended_retention_bonus', sa.Numeric(precision=12, scale=2), server_default='0.00', nullable=False),
        sa.Column('recommended_stock_options', sa.Integer(), server_default='0', nullable=False),
        sa.Column('recommend_promotion', sa.Boolean(), nullable=False),
        sa.Column('recommended_title', sa.String(length=100), nullable=True),
        sa.Column('recommended_increment_percentage', sa.Numeric(precision=5, scale=2), server_default='0.00', nullable=False),
        sa.Column('market_ratio', sa.Numeric(precision=3, scale=2), server_default='1.00', nullable=False),
        sa.Column('equity_status', sa.String(length=50), server_default='COMPLIANT', nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('compiled_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_compensation_recs_employee_id', 'ai_compensation_recommendations', ['employee_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_compensation_recs_employee_id', table_name='ai_compensation_recommendations')
    op.drop_table('ai_compensation_recommendations')
    op.drop_index('ix_benchmarks_designation_exp', table_name='market_compensation_benchmarks')
    op.drop_table('market_compensation_benchmarks')
