"""Add Performance AI management tables

Revision ID: 82e71255c2ea
Revises: eedfbcfcb2ff
Create Date: 2026-07-06 10:08:44.989256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82e71255c2ea'
down_revision: Union[str, None] = 'eedfbcfcb2ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create performance_review_cycles table
    op.create_table(
        'performance_review_cycles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='ACTIVE', nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. create employee_performance_goals table
    op.create_table(
        'employee_performance_goals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_value', sa.String(length=100), nullable=False),
        sa.Column('current_value', sa.String(length=100), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_performance_goals_employee_id', 'employee_performance_goals', ['employee_id'], unique=False)

    # 3. create performance_reviews table
    op.create_table(
        'performance_reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('cycle_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('reviewer_id', sa.UUID(), nullable=True),
        sa.Column('self_rating', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('reviewer_rating', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('ai_overall_score', sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column('ai_review_justification', sa.Text(), nullable=True),
        sa.Column('promotion_recommendation', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('salary_increment_percentage', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('feedback_360', sa.JSON(), nullable=True),
        sa.Column('skill_gap_analysis', sa.JSON(), nullable=True),
        sa.Column('learning_recommendations', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['cycle_id'], ['performance_review_cycles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_performance_reviews_cycle_id', 'performance_reviews', ['cycle_id'], unique=False)
    op.create_index('ix_performance_reviews_employee_id', 'performance_reviews', ['employee_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_performance_reviews_employee_id', table_name='performance_reviews')
    op.drop_index('ix_performance_reviews_cycle_id', table_name='performance_reviews')
    op.drop_table('performance_reviews')
    op.drop_index('ix_performance_goals_employee_id', table_name='employee_performance_goals')
    op.drop_table('employee_performance_goals')
    op.drop_table('performance_review_cycles')
