"""Add AI Email Generator tables

Revision ID: 12f939d81c44
Revises: c814ce76d52f
Create Date: 2026-07-06 10:31:08.147408

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12f939d81c44'
down_revision: Union[str, None] = 'c814ce76d52f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create generated_email_logs table
    op.create_table(
        'generated_email_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('email_type', sa.String(length=50), nullable=False),
        sa.Column('tone', sa.String(length=20), server_default='PROFESSIONAL', nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_generated_emails_company_id', 'generated_email_logs', ['company_id'], unique=False)
    op.create_index('ix_generated_emails_type', 'generated_email_logs', ['email_type'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_generated_emails_type', table_name='generated_email_logs')
    op.drop_index('ix_generated_emails_company_id', table_name='generated_email_logs')
    op.drop_table('generated_email_logs')
