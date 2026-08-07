"""Add AI Behavioural Interview tables

Revision ID: c814ce76d52f
Revises: 4ad46d158471
Create Date: 2026-07-06 10:28:54.184915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c814ce76d52f'
down_revision: Union[str, None] = '4ad46d158471'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create behavioural_interview_sessions table
    op.create_table(
        'behavioural_interview_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(length=100), nullable=False),
        sa.Column('experience_years', sa.Integer(), nullable=False),
        sa.Column('seniority', sa.String(length=50), nullable=False),
        sa.Column('company_culture', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_behavioural_sessions_company_id', 'behavioural_interview_sessions', ['company_id'], unique=False)

    # 2. create behavioural_interview_questions table
    op.create_table(
        'behavioural_interview_questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('dimension', sa.String(length=50), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('candidate_response', sa.Text(), nullable=True),
        sa.Column('evaluation_score', sa.Integer(), nullable=True),
        sa.Column('evaluation_feedback', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['behavioural_interview_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('behavioural_interview_questions')
    op.drop_index('ix_behavioural_sessions_company_id', table_name='behavioural_interview_sessions')
    op.drop_table('behavioural_interview_sessions')
