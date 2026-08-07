"""Add document analysis tables

Revision ID: 44ddb61b2566
Revises: 77be3579f5e3
Create Date: 2026-07-05 10:06:36.894831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44ddb61b2566'
down_revision: Union[str, None] = '77be3579f5e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create analyzed_documents table
    op.create_table(
        'analyzed_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_type', sa.String(length=20), nullable=False),
        sa.Column('file_checksum', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='PENDING', nullable=False),
        sa.Column('ocr_engine', sa.String(length=50), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('classification', sa.String(length=50), nullable=True),
        sa.Column('classification_confidence', sa.Float(), nullable=True),
        sa.Column('extracted_data', sa.JSON(), nullable=True),
        sa.Column('summary_executive', sa.Text(), nullable=True),
        sa.Column('summary_detailed', sa.Text(), nullable=True),
        sa.Column('key_highlights', sa.JSON(), nullable=True),
        sa.Column('missing_info', sa.JSON(), nullable=True),
        sa.Column('compliance_report', sa.JSON(), nullable=True),
        sa.Column('risk_analysis', sa.JSON(), nullable=True),
        sa.Column('ai_recommendations', sa.JSON(), nullable=True),
        sa.Column('health_score', sa.Float(), nullable=False, default=1.0),
        sa.Column('validation_results', sa.JSON(), nullable=True),
        sa.Column('validation_status', sa.String(length=30), server_default='UNVALIDATED', nullable=False),
        sa.Column('embedding_indexed', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('uploaded_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_analyzed_docs_checksum', 'analyzed_documents', ['file_checksum'], unique=False)
    op.create_index('ix_analyzed_docs_status', 'analyzed_documents', ['status'], unique=False)
    op.create_index('ix_analyzed_docs_classification', 'analyzed_documents', ['classification'], unique=False)

    # 2. Create document_analysis_versions table
    op.create_table(
        'document_analysis_versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_checksum', sa.String(length=64), nullable=False),
        sa.Column('uploaded_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['analyzed_documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # 3. Create document_comparison_runs table
    op.create_table(
        'document_comparison_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('source_document_id', sa.UUID(), nullable=False),
        sa.Column('target_document_id', sa.UUID(), nullable=False),
        sa.Column('similarity_score', sa.Float(), nullable=False),
        sa.Column('differences', sa.JSON(), nullable=True),
        sa.Column('missing_info', sa.JSON(), nullable=True),
        sa.Column('changed_fields', sa.JSON(), nullable=True),
        sa.Column('fraud_signals', sa.JSON(), nullable=True),
        sa.Column('compared_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['compared_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_document_id'], ['analyzed_documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_document_id'], ['analyzed_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_doc_comparisons_left', 'document_comparison_runs', ['source_document_id'], unique=False)
    op.create_index('ix_doc_comparisons_right', 'document_comparison_runs', ['target_document_id'], unique=False)

    # 4. Create analysis_audit_logs table
    op.create_table(
        'analysis_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('document_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['analyzed_documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_analysis_audit_user', 'analysis_audit_logs', ['user_id'], unique=False)
    op.create_index('ix_analysis_audit_doc', 'analysis_audit_logs', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_analysis_audit_doc', table_name='analysis_audit_logs')
    op.drop_index('ix_analysis_audit_user', table_name='analysis_audit_logs')
    op.drop_table('analysis_audit_logs')
    op.drop_index('ix_doc_comparisons_right', table_name='document_comparison_runs')
    op.drop_index('ix_doc_comparisons_left', table_name='document_comparison_runs')
    op.drop_table('document_comparison_runs')
    op.drop_table('document_analysis_versions')
    op.drop_index('ix_analyzed_docs_classification', table_name='analyzed_documents')
    op.drop_index('ix_analyzed_docs_status', table_name='analyzed_documents')
    op.drop_index('ix_analyzed_docs_checksum', table_name='analyzed_documents')
    op.drop_table('analyzed_documents')
