"""Add Company Policy Explainer tables

Revision ID: 403333c2eb75
Revises: 82e71255c2ea
Create Date: 2026-07-06 10:12:34.990922

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '403333c2eb75'
down_revision: Union[str, None] = '82e71255c2ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create company_policy_documents table
    op.create_table(
        'company_policy_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('raw_content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_policy_documents_company_id', 'company_policy_documents', ['company_id'], unique=False)

    # 2. create company_policy_chunks table
    op.create_table(
        'company_policy_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_document_id', sa.UUID(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('vector', sa.JSON(), nullable=False),
        sa.Column('chunk_order', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['policy_document_id'], ['company_policy_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_policy_chunks_doc_id', 'company_policy_chunks', ['policy_document_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_policy_chunks_doc_id', table_name='company_policy_chunks')
    op.drop_table('company_policy_chunks')
    op.drop_index('ix_policy_documents_company_id', table_name='company_policy_documents')
    op.drop_table('company_policy_documents')
