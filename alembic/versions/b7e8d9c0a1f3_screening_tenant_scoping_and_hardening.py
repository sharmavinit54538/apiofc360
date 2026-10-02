"""screening tenant scoping and production hardening

Revision ID: b7e8d9c0a1f3
Revises: e7d8c9b0a1f2
Create Date: 2026-10-01 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7e8d9c0a1f3'
down_revision: Union[str, None] = 'e7d8c9b0a1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add company_id and indexes to ai_resume_documents, candidate_match_scores, ai_screening_results
    op.add_column(
        'ai_resume_documents',
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True)
    )
    op.create_index('ix_ai_resume_documents_company_id', 'ai_resume_documents', ['company_id'], unique=False)

    op.add_column(
        'candidate_match_scores',
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True)
    )
    op.create_index('ix_candidate_match_scores_company_id', 'candidate_match_scores', ['company_id'], unique=False)

    op.add_column(
        'ai_screening_results',
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True)
    )
    op.create_index('ix_ai_screening_results_company_id', 'ai_screening_results', ['company_id'], unique=False)

    # 2. Make application_id and decision nullable in ai_screening_results
    op.alter_column('ai_screening_results', 'application_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column('ai_screening_results', 'decision', existing_type=sa.String(length=20), nullable=True)

    # 3. Add status, match_score, human decision, compliance, and run tracking columns to ai_screening_results
    op.add_column('ai_screening_results', sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'COMPLETED'")))
    op.add_column('ai_screening_results', sa.Column('match_score', sa.Float(), nullable=True))
    op.add_column('ai_screening_results', sa.Column('human_decision', sa.String(length=20), nullable=True))
    op.add_column('ai_screening_results', sa.Column('human_decision_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.add_column('ai_screening_results', sa.Column('human_decision_reason', sa.Text(), nullable=True))
    op.add_column('ai_screening_results', sa.Column('human_decision_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('ai_screening_results', sa.Column('prompt_version', sa.String(length=50), nullable=True))
    op.add_column('ai_screening_results', sa.Column('thresholds_used', sa.JSON(), nullable=True))
    op.add_column('ai_screening_results', sa.Column('input_hash', sa.String(length=64), nullable=True))
    op.add_column('ai_screening_results', sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('ai_screening_results', sa.Column('error_message', sa.Text(), nullable=True))

    op.create_index('ix_ai_screening_results_status', 'ai_screening_results', ['status'], unique=False)
    op.create_index('ix_ai_screening_results_run_id', 'ai_screening_results', ['run_id'], unique=False)

    # 4. Backfill company_id from parent relations (applications and jobs)
    op.execute("""
        UPDATE ai_resume_documents d
        SET company_id = a.company_id
        FROM applications a
        WHERE d.application_id = a.id AND a.company_id IS NOT NULL;
    """)

    op.execute("""
        UPDATE ai_screening_results s
        SET company_id = j.company_id
        FROM jobs j
        WHERE s.job_id = j.id AND j.company_id IS NOT NULL;
    """)

    op.execute("""
        UPDATE candidate_match_scores m
        SET company_id = j.company_id
        FROM jobs j
        WHERE m.job_id = j.id AND j.company_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.drop_index('ix_ai_screening_results_run_id', table_name='ai_screening_results')
    op.drop_index('ix_ai_screening_results_status', table_name='ai_screening_results')
    op.drop_column('ai_screening_results', 'error_message')
    op.drop_column('ai_screening_results', 'run_id')
    op.drop_column('ai_screening_results', 'input_hash')
    op.drop_column('ai_screening_results', 'thresholds_used')
    op.drop_column('ai_screening_results', 'prompt_version')
    op.drop_column('ai_screening_results', 'human_decision_at')
    op.drop_column('ai_screening_results', 'human_decision_reason')
    op.drop_column('ai_screening_results', 'human_decision_by')
    op.drop_column('ai_screening_results', 'human_decision')
    op.drop_column('ai_screening_results', 'match_score')
    op.drop_column('ai_screening_results', 'status')

    op.alter_column('ai_screening_results', 'decision', existing_type=sa.String(length=20), nullable=False)
    op.alter_column('ai_screening_results', 'application_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_index('ix_ai_screening_results_company_id', table_name='ai_screening_results')
    op.drop_column('ai_screening_results', 'company_id')

    op.drop_index('ix_candidate_match_scores_company_id', table_name='candidate_match_scores')
    op.drop_column('candidate_match_scores', 'company_id')

    op.drop_index('ix_ai_resume_documents_company_id', table_name='ai_resume_documents')
    op.drop_column('ai_resume_documents', 'company_id')
