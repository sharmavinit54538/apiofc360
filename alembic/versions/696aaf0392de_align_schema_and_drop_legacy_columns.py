"""align_schema_and_drop_legacy_columns

Revision ID: 696aaf0392de
Revises: 989bb686d85a
Create Date: 2026-09-30 10:26:43.517882

Resolves all remaining schema drift between SQLAlchemy models and PostgreSQL database:
1. Category C: Widen DB columns to match models (employee_documents.document_type, payroll_runs.status,
   refresh_tokens.token_hash, refresh_tokens.parent_token_hash, overtime multipliers to Numeric(5, 2)).
2. Category E: Backfill and enforce NOT NULL + server_default for statutory compliance banking fields
   (bank_name, bank_ifsc, salary_transfer_format).
3. Category D2: Idempotently drop legacy unused columns, foreign keys, unique constraints, and indexes
   from old school SaaS (tenant_id, school_id, avatar, created_by, status, extra_permissions on users;
   tenant_id on refresh_tokens and audit_logs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '696aaf0392de'
down_revision: Union[str, None] = '989bb686d85a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # =========================================================================
    # 1. CATEGORY C: Widen columns in DB where narrower than model
    # =========================================================================
    if 'employee_documents' in tables:
        cols = {c['name']: c for c in insp.get_columns('employee_documents')}
        if 'document_type' in cols:
            op.alter_column(
                'employee_documents',
                'document_type',
                existing_type=sa.String(30),
                type_=sa.String(100),
                existing_nullable=False,
            )

    if 'payroll_runs' in tables:
        cols = {c['name']: c for c in insp.get_columns('payroll_runs')}
        if 'status' in cols:
            op.alter_column(
                'payroll_runs',
                'status',
                existing_type=sa.String(20),
                type_=sa.String(30),
                existing_nullable=False,
            )

    if 'refresh_tokens' in tables:
        cols = {c['name']: c for c in insp.get_columns('refresh_tokens')}
        if 'token_hash' in cols:
            op.alter_column(
                'refresh_tokens',
                'token_hash',
                existing_type=sa.String(64),
                type_=sa.String(255),
                existing_nullable=False,
            )
        if 'parent_token_hash' in cols:
            op.alter_column(
                'refresh_tokens',
                'parent_token_hash',
                existing_type=sa.String(64),
                type_=sa.String(255),
                existing_nullable=True,
            )

    if 'statutory_compliance_configs' in tables:
        cols = {c['name']: c for c in insp.get_columns('statutory_compliance_configs')}
        for col_name, s_default in [
            ('overtime_multiplier_holiday', '2.00'),
            ('overtime_multiplier_night', '1.25'),
            ('overtime_multiplier_weekend', '1.50'),
        ]:
            if col_name in cols:
                op.alter_column(
                    'statutory_compliance_configs',
                    col_name,
                    existing_type=sa.Numeric(3, 2),
                    type_=sa.Numeric(5, 2),
                    existing_nullable=False,
                    server_default=sa.text(s_default),
                )

    # =========================================================================
    # 2. CATEGORY E: Backfill and NOT NULL for banking fields
    # =========================================================================
    if 'statutory_compliance_configs' in tables:
        # Backfill NULL values first to avoid constraint violation
        op.execute("UPDATE statutory_compliance_configs SET bank_name = 'HDFC Bank' WHERE bank_name IS NULL")
        op.execute("UPDATE statutory_compliance_configs SET bank_ifsc = 'HDFC0001234' WHERE bank_ifsc IS NULL")
        op.execute("UPDATE statutory_compliance_configs SET salary_transfer_format = 'NEFT' WHERE salary_transfer_format IS NULL")

        op.alter_column(
            'statutory_compliance_configs',
            'bank_name',
            existing_type=sa.String(100),
            nullable=False,
            server_default=sa.text("'HDFC Bank'"),
        )
        op.alter_column(
            'statutory_compliance_configs',
            'bank_ifsc',
            existing_type=sa.String(20),
            nullable=False,
            server_default=sa.text("'HDFC0001234'"),
        )
        op.alter_column(
            'statutory_compliance_configs',
            'salary_transfer_format',
            existing_type=sa.String(50),
            nullable=False,
            server_default=sa.text("'NEFT'"),
        )

    # =========================================================================
    # 3. CATEGORY D2: Drop legacy unused columns, constraints, and indexes
    # =========================================================================
    # 3a. Table: users
    if 'users' in tables:
        # Drop FK constraint first
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_created_by_users;")
        # Drop unique constraint
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_tenant_email;")
        # Drop indexes
        op.execute("DROP INDEX IF EXISTS ix_users_tenant_id;")
        op.execute("DROP INDEX IF EXISTS ix_users_school_id;")

        # Drop legacy columns
        for col in [
            'created_by',
            'tenant_id',
            'school_id',
            'avatar',
            'status',
            'extra_permissions',
        ]:
            op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {col};")

    # 3b. Table: refresh_tokens
    if 'refresh_tokens' in tables:
        op.execute("DROP INDEX IF EXISTS ix_refresh_tokens_tenant_id;")
        op.execute("ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS tenant_id;")

    # 3c. Table: audit_logs
    if 'audit_logs' in tables:
        op.execute("DROP INDEX IF EXISTS ix_audit_logs_tenant_id;")
        op.execute("ALTER TABLE audit_logs DROP COLUMN IF EXISTS tenant_id;")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # Re-add legacy columns to audit_logs
    if 'audit_logs' in tables:
        cols = {c['name'] for c in insp.get_columns('audit_logs')}
        if 'tenant_id' not in cols:
            op.add_column('audit_logs', sa.Column('tenant_id', sa.String(36), nullable=True))
            op.create_index('ix_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])

    # Re-add legacy columns to refresh_tokens
    if 'refresh_tokens' in tables:
        cols = {c['name'] for c in insp.get_columns('refresh_tokens')}
        if 'tenant_id' not in cols:
            op.add_column('refresh_tokens', sa.Column('tenant_id', sa.String(36), nullable=True))
            op.create_index('ix_refresh_tokens_tenant_id', 'refresh_tokens', ['tenant_id'])

        if 'parent_token_hash' in cols:
            op.alter_column('refresh_tokens', 'parent_token_hash', type_=sa.String(64), existing_type=sa.String(255))
        if 'token_hash' in cols:
            op.alter_column('refresh_tokens', 'token_hash', type_=sa.String(64), existing_type=sa.String(255))

    # Re-add legacy columns to users
    if 'users' in tables:
        cols = {c['name'] for c in insp.get_columns('users')}
        if 'tenant_id' not in cols:
            op.add_column('users', sa.Column('tenant_id', sa.String(36), nullable=True))
            op.create_index('ix_users_tenant_id', 'users', ['tenant_id'])
        if 'school_id' not in cols:
            op.add_column('users', sa.Column('school_id', sa.String(36), nullable=True))
            op.create_index('ix_users_school_id', 'users', ['school_id'])
        if 'avatar' not in cols:
            op.add_column('users', sa.Column('avatar', sa.String(1024), nullable=True))
        if 'status' not in cols:
            op.add_column('users', sa.Column('status', sa.String(16), nullable=True))
        if 'extra_permissions' not in cols:
            op.add_column('users', sa.Column('extra_permissions', sa.String(2048), nullable=True))
        if 'created_by' not in cols:
            op.add_column('users', sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True))

    # Revert statutory compliance columns
    if 'statutory_compliance_configs' in tables:
        op.alter_column('statutory_compliance_configs', 'bank_name', nullable=True, server_default=None)
        op.alter_column('statutory_compliance_configs', 'bank_ifsc', nullable=True, server_default=None)
        op.alter_column('statutory_compliance_configs', 'salary_transfer_format', nullable=True, server_default=None)
        for col_name in ['overtime_multiplier_holiday', 'overtime_multiplier_night', 'overtime_multiplier_weekend']:
            op.alter_column('statutory_compliance_configs', col_name, type_=sa.Numeric(3, 2), existing_type=sa.Numeric(5, 2))

    # Revert payroll_runs and employee_documents
    if 'payroll_runs' in tables:
        op.alter_column('payroll_runs', 'status', type_=sa.String(20), existing_type=sa.String(30))
    if 'employee_documents' in tables:
        op.alter_column('employee_documents', 'document_type', type_=sa.String(30), existing_type=sa.String(100))
