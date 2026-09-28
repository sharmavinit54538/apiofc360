"""update document management schema for audit, signatures, hash, categories and company scoping

Revision ID: d1a2b3c4d5e7
Revises: c1a2b3c4d5e6
Create Date: 2026-09-28 08:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = 'd1a2b3c4d5e7'
down_revision = 'c1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. document_categories: add group column and seed canonical categories
    if 'document_categories' in tables:
        doc_cat_cols = {c['name'] for c in inspector.get_columns('document_categories')}
        if 'group' not in doc_cat_cols:
            op.add_column('document_categories', sa.Column('group', sa.String(length=50), nullable=True))

    # 2. document_signatures: created_at, document_hash, partial unique index
    if 'document_signatures' in tables:
        sig_cols = {c['name'] for c in inspector.get_columns('document_signatures')}
        if 'document_hash' not in sig_cols:
            op.add_column('document_signatures', sa.Column('document_hash', sa.String(length=64), nullable=True))
        if 'created_at' not in sig_cols:
            op.add_column(
                'document_signatures',
                sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            )
        # Add partial unique index
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('document_signatures')}
        if 'uq_doc_signatures_pending_partial' not in existing_indexes:
            op.create_index(
                'uq_doc_signatures_pending_partial',
                'document_signatures',
                ['employee_doc_id', 'signer_user_id'],
                unique=True,
                postgresql_where=sa.text("status = 'PENDING'"),
            )

    # 3. employee_documents: document_hash
    if 'employee_documents' in tables:
        emp_doc_cols = {c['name'] for c in inspector.get_columns('employee_documents')}
        if 'document_hash' not in emp_doc_cols:
            op.add_column('employee_documents', sa.Column('document_hash', sa.String(length=64), nullable=True))

    # 4. document_versions: document_hash
    if 'document_versions' in tables:
        ver_cols = {c['name'] for c in inspector.get_columns('document_versions')}
        if 'document_hash' not in ver_cols:
            op.add_column('document_versions', sa.Column('document_hash', sa.String(length=64), nullable=True))

    # 5. document_templates: company_id
    if 'document_templates' in tables:
        tmpl_cols = {c['name'] for c in inspector.get_columns('document_templates')}
        if 'company_id' not in tmpl_cols:
            op.add_column('document_templates', sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True))
            op.create_foreign_key(
                op.f('fk_document_templates_company_id_companies'),
                'document_templates',
                'companies',
                ['company_id'],
                ['id'],
                ondelete='CASCADE',
            )

    # 6. document_audit_logs: company_id
    if 'document_audit_logs' in tables:
        audit_cols = {c['name'] for c in inspector.get_columns('document_audit_logs')}
        if 'company_id' not in audit_cols:
            op.add_column('document_audit_logs', sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True))
            op.create_foreign_key(
                op.f('fk_document_audit_logs_company_id_companies'),
                'document_audit_logs',
                'companies',
                ['company_id'],
                ['id'],
                ondelete='CASCADE',
            )

    # 7. Seed canonical categories idempotently
    from app.services.document_categories import CANONICAL_CATEGORIES, LEGACY_CODE_TO_GROUP
    # Update existing categories
    for code, group_name in LEGACY_CODE_TO_GROUP.items():
        bind.execute(
            sa.text("UPDATE document_categories SET \"group\" = :grp WHERE lower(code) = :code AND (\"group\" IS NULL OR \"group\" = '')"),
            {"grp": group_name, "code": code.lower()},
        )
    for item in CANONICAL_CATEGORIES:
        bind.execute(
            sa.text("UPDATE document_categories SET \"group\" = :grp WHERE upper(code) = :code AND (\"group\" IS NULL OR \"group\" = '')"),
            {"grp": item["group"], "code": item["code"].upper()},
        )
        # Check existence
        row = bind.execute(
            sa.text("SELECT id FROM document_categories WHERE upper(code) = :code"),
            {"code": item["code"].upper()},
        ).fetchone()
        if not row:
            bind.execute(
                sa.text("INSERT INTO document_categories (id, name, code, \"group\", is_company) VALUES (:id, :name, :code, :grp, :is_company)"),
                {
                    "id": str(uuid.uuid4()),
                    "name": item["name"],
                    "code": item["code"],
                    "grp": item["group"],
                    "is_company": item["is_company"],
                },
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'document_audit_logs' in tables:
        op.drop_constraint(op.f('fk_document_audit_logs_company_id_companies'), 'document_audit_logs', type_='foreignkey')
        op.drop_column('document_audit_logs', 'company_id')

    if 'document_templates' in tables:
        op.drop_constraint(op.f('fk_document_templates_company_id_companies'), 'document_templates', type_='foreignkey')
        op.drop_column('document_templates', 'company_id')

    if 'document_versions' in tables:
        op.drop_column('document_versions', 'document_hash')

    if 'employee_documents' in tables:
        op.drop_column('employee_documents', 'document_hash')

    if 'document_signatures' in tables:
        op.drop_index('uq_doc_signatures_pending_partial', table_name='document_signatures')
        op.drop_column('document_signatures', 'document_hash')
        op.drop_column('document_signatures', 'created_at')

    if 'document_categories' in tables:
        op.drop_column('document_categories', 'group')
