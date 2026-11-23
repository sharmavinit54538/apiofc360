"""Add interview invitations, candidate company_id, and AI interview enhancements

Revision ID: 383fd82fdc00
Revises: a7dd8d9bc88f
Create Date: 2026-11-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '383fd82fdc00'
down_revision: Union[str, None] = 'a7dd8d9bc88f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Add company_id to candidates table ###
    op.add_column('candidates', sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_candidates_company_id', 'candidates', 'companies', ['company_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_candidates_company_id', 'candidates', ['company_id'], unique=False)
    op.create_index('ix_candidates_email_company', 'candidates', ['email', 'company_id'], unique=True)
    
    # Remove old unique constraint on email (now composite with company_id)
    op.drop_constraint('uq_candidates_email', 'candidates', type_='unique')
    
    # ### Add invitation token columns to interview_schedules ###
    op.add_column('interview_schedules', sa.Column('invitation_token', sa.String(length=500), nullable=True))
    op.add_column('interview_schedules', sa.Column('invitation_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('interview_schedules', sa.Column('invitation_used_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_interview_schedules_invitation_token', 'interview_schedules', ['invitation_token'])
    
    # ### Create interview_invitations table ###
    op.create_table(
        'interview_invitations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('interview_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('round_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('token', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='SENT'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('device_check_completed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('consent_given', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grace_period_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reconnect_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('max_reconnects', sa.Integer(), nullable=False, server_default=sa.text('3')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_interview_invitations_company_id'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['interview_id'], ['interviews.id'], name=op.f('fk_interview_invitations_interview_id'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], name=op.f('fk_interview_invitations_candidate_id'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['round_id'], ['interview_rounds.id'], name=op.f('fk_interview_invitations_round_id'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_invitations')),
        sa.UniqueConstraint('token', name=op.f('uq_interview_invitations_token')),
    )
    op.create_index('ix_interview_invitations_interview', 'interview_invitations', ['interview_id'], unique=False)
    op.create_index('ix_interview_invitations_candidate', 'interview_invitations', ['candidate_id'], unique=False)
    op.create_index('ix_interview_invitations_status', 'interview_invitations', ['status'], unique=False)
    op.create_index('ix_interview_invitations_token', 'interview_invitations', ['token'], unique=True)


def downgrade() -> None:
    # ### Drop interview_invitations table ###
    op.drop_index('ix_interview_invitations_token', table_name='interview_invitations')
    op.drop_index('ix_interview_invitations_status', table_name='interview_invitations')
    op.drop_index('ix_interview_invitations_candidate', table_name='interview_invitations')
    op.drop_index('ix_interview_invitations_interview', table_name='interview_invitations')
    op.drop_table('interview_invitations')
    
    # ### Remove invitation token columns from interview_schedules ###
    op.drop_constraint('uq_interview_schedules_invitation_token', 'interview_schedules', type_='unique')
    op.drop_column('interview_schedules', 'invitation_used_at')
    op.drop_column('interview_schedules', 'invitation_expires_at')
    op.drop_column('interview_schedules', 'invitation_token')
    
    # ### Restore candidates table ###
    op.drop_index('ix_candidates_email_company', table_name='candidates')
    op.drop_index('ix_candidates_company_id', table_name='candidates')
    op.drop_constraint('fk_candidates_company_id', 'candidates', type_='foreignkey')
    op.drop_column('candidates', 'company_id')
    op.create_unique_constraint('uq_candidates_email', 'candidates', ['email'])