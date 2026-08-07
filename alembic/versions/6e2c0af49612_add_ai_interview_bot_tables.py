"""Add AI interview bot tables

Revision ID: 6e2c0af49612
Revises: ccb36a901b6d
Create Date: 2026-07-06 09:46:55.564532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e2c0af49612'
down_revision: Union[str, None] = 'ccb36a901b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create ai_interview_sessions table
    op.create_table(
        'ai_interview_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('candidate_id', sa.UUID(), nullable=False),
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('interview_round_id', sa.UUID(), nullable=True),
        sa.Column('interview_type', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='SCHEDULED', nullable=False),
        sa.Column('current_question_index', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['interview_round_id'], ['interview_rounds.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ai_interview_sessions_candidate', 'ai_interview_sessions', ['candidate_id'], unique=False)
    op.create_index('ix_ai_interview_sessions_status', 'ai_interview_sessions', ['status'], unique=False)

    # 2. create ai_interview_questions table
    op.create_table(
        'ai_interview_questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('interview_session_id', sa.UUID(), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('question_type', sa.String(length=30), nullable=False),
        sa.Column('expected_answer', sa.Text(), nullable=True),
        sa.Column('difficulty', sa.String(length=20), server_default='MEDIUM', nullable=False),
        sa.Column('order_index', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['interview_session_id'], ['ai_interview_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 3. create ai_interview_responses table
    op.create_table(
        'ai_interview_responses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('interview_session_id', sa.UUID(), nullable=False),
        sa.Column('question_id', sa.UUID(), nullable=False),
        sa.Column('candidate_response', sa.Text(), nullable=False),
        sa.Column('code_output', sa.Text(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), server_default='0', nullable=False),
        sa.Column('emotion_analysis', sa.JSON(), nullable=True),
        sa.Column('communication_analysis', sa.JSON(), nullable=True),
        sa.Column('proctoring_flags', sa.JSON(), nullable=True),
        sa.Column('score', sa.Integer(), server_default='0', nullable=False),
        sa.Column('evaluation_feedback', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['interview_session_id'], ['ai_interview_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['ai_interview_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. create ai_interview_scorecards table
    op.create_table(
        'ai_interview_scorecards',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('interview_session_id', sa.UUID(), nullable=False),
        sa.Column('scorecard_submission_id', sa.UUID(), nullable=True),
        sa.Column('anti_cheating_report', sa.JSON(), nullable=True),
        sa.Column('emotion_summary', sa.JSON(), nullable=True),
        sa.Column('communication_summary', sa.JSON(), nullable=True),
        sa.Column('final_hiring_recommendation', sa.String(length=20), nullable=False),
        sa.Column('overall_justification', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['interview_session_id'], ['ai_interview_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scorecard_submission_id'], ['scorecard_submissions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('ai_interview_scorecards')
    op.drop_table('ai_interview_responses')
    op.drop_table('ai_interview_questions')
    op.drop_index('ix_ai_interview_sessions_status', table_name='ai_interview_sessions')
    op.drop_index('ix_ai_interview_sessions_candidate', table_name='ai_interview_sessions')
    op.drop_table('ai_interview_sessions')
