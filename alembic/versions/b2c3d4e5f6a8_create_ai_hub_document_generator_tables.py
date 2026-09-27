"""create ai hub document generator tables

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-27 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'generated_documents' not in existing_tables:
        op.create_table(
            'generated_documents',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('company_id', sa.UUID(), nullable=True),
            sa.Column('template_id', sa.UUID(), nullable=True),
            sa.Column('title', sa.String(length=255), nullable=False),
            sa.Column('variables', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True),
            sa.Column('format', sa.String(length=20), server_default='pdf', nullable=False),
            sa.Column('file_path_or_url', sa.String(length=500), nullable=False),
            sa.Column('generated_by', sa.UUID(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['template_id'], ['document_templates.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['generated_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('generated_documents')} if 'generated_documents' in inspector.get_table_names() else set()
    if 'ix_generated_docs_company_id' not in existing_indexes:
        op.create_index('ix_generated_docs_company_id', 'generated_documents', ['company_id'], unique=False)
    if 'ix_generated_docs_template_id' not in existing_indexes:
        op.create_index('ix_generated_docs_template_id', 'generated_documents', ['template_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_generated_docs_template_id', table_name='generated_documents')
    op.drop_index('ix_generated_docs_company_id', table_name='generated_documents')
    op.drop_table('generated_documents')
