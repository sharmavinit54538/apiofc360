"""fix auth schema completeness — add missing refresh_token columns and create security tables

Revision ID: 2a3b4c5d6e7f
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-17 10:25:00.000000

Non-destructive, production-safe migration that:
1. Adds 3 missing columns to refresh_tokens (family_id, parent_token_hash, revoked_reason)
2. Adds missing ix_refresh_tokens_family_id index
3. Creates 5 actively-used security tables that had models + API routes but no migration

All operations use IF NOT EXISTS guards for idempotent safety in case tables/columns
were previously created outside of Alembic (e.g. via Base.metadata.create_all()).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2a3b4c5d6e7f'
down_revision: Union[str, None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column exists on the given table via information_schema."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :tbl AND column_name = :col"
    ), {"tbl": table, "col": column}).scalar()
    return result is not None


def _table_exists(table: str) -> bool:
    """Check if a table exists in the public schema."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :tbl"
    ), {"tbl": table}).scalar()
    return result is not None


def _index_exists(index_name: str) -> bool:
    """Check if an index exists in PostgreSQL."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE indexname = :idx"
    ), {"idx": index_name}).scalar()
    return result is not None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────
    # PART 1: Add missing columns to refresh_tokens
    # ──────────────────────────────────────────────────────────────────────

    if not _column_exists('refresh_tokens', 'family_id'):
        op.add_column(
            'refresh_tokens',
            sa.Column('family_id', postgresql.UUID(as_uuid=True), nullable=True),
        )

    if not _column_exists('refresh_tokens', 'parent_token_hash'):
        op.add_column(
            'refresh_tokens',
            sa.Column('parent_token_hash', sa.String(64), nullable=True),
        )

    if not _column_exists('refresh_tokens', 'revoked_reason'):
        op.add_column(
            'refresh_tokens',
            sa.Column('revoked_reason', sa.String(100), nullable=True),
        )

    # Add family_id index if missing
    if not _index_exists('ix_refresh_tokens_family_id'):
        op.create_index(
            'ix_refresh_tokens_family_id',
            'refresh_tokens',
            ['family_id'],
            unique=False,
        )

    # ──────────────────────────────────────────────────────────────────────
    # PART 2: Create actively-used security tables
    # ──────────────────────────────────────────────────────────────────────

    # 2a. security_roles
    if not _table_exists('security_roles'):
        op.create_table(
            'security_roles',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('role_name', sa.String(100), nullable=False),
            sa.Column('role_code', sa.String(50), nullable=False),
            sa.Column('description', sa.String(255), nullable=True),
            sa.Column('is_system_role', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_security_roles')),
            sa.ForeignKeyConstraint(
                ['company_id'], ['companies.id'],
                name=op.f('fk_security_roles_company_id_companies'),
                ondelete='CASCADE',
            ),
            sa.UniqueConstraint('role_code', name=op.f('uq_security_roles_role_code')),
        )

    # 2b. security_policies
    if not _table_exists('security_policies'):
        op.create_table(
            'security_policies',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('session_timeout_minutes', sa.Integer(), nullable=False, server_default=sa.text('30')),
            sa.Column('idle_timeout_minutes', sa.Integer(), nullable=False, server_default=sa.text('15')),
            sa.Column('max_concurrent_sessions', sa.Integer(), nullable=False, server_default=sa.text('3')),
            sa.Column('min_password_length', sa.Integer(), nullable=False, server_default=sa.text('12')),
            sa.Column('require_uppercase', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('require_lowercase', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('require_numbers', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('require_special_chars', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('aes_256_encryption_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('mask_salary_non_payroll', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_security_policies')),
            sa.ForeignKeyConstraint(
                ['company_id'], ['companies.id'],
                name=op.f('fk_security_policies_company_id_companies'),
                ondelete='CASCADE',
            ),
        )

    # 2c. user_sessions
    if not _table_exists('user_sessions'):
        op.create_table(
            'user_sessions',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_email', sa.String(100), nullable=False),
            sa.Column('device_info', sa.String(255), nullable=False),
            sa.Column('browser', sa.String(100), nullable=False),
            sa.Column('ip_address', sa.String(50), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
            sa.Column('login_time', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.Column('last_activity', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions')),
        )

    # 2d. ip_whitelist
    if not _table_exists('ip_whitelist'):
        op.create_table(
            'ip_whitelist',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('ip_address_or_range', sa.String(50), nullable=False),
            sa.Column('description', sa.String(255), nullable=True),
            sa.Column('created_by', sa.String(100), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_ip_whitelist')),
            sa.ForeignKeyConstraint(
                ['company_id'], ['companies.id'],
                name=op.f('fk_ip_whitelist_company_id_companies'),
                ondelete='CASCADE',
            ),
        )

    # 2e. security_audit_logs
    if not _table_exists('security_audit_logs'):
        op.create_table(
            'security_audit_logs',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('action', sa.String(50), nullable=False),
            sa.Column('actor', sa.String(100), nullable=False),
            sa.Column('details', sa.Text(), nullable=False),
            sa.Column('ip_address', sa.String(50), nullable=True),
            sa.Column('browser', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_security_audit_logs')),
        )


def downgrade() -> None:
    # Drop security tables (reverse order of creation)
    for table in ('security_audit_logs', 'ip_whitelist', 'user_sessions', 'security_policies', 'security_roles'):
        if _table_exists(table):
            op.drop_table(table)

    # Remove added columns from refresh_tokens
    if _index_exists('ix_refresh_tokens_family_id'):
        op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')

    if _column_exists('refresh_tokens', 'revoked_reason'):
        op.drop_column('refresh_tokens', 'revoked_reason')

    if _column_exists('refresh_tokens', 'parent_token_hash'):
        op.drop_column('refresh_tokens', 'parent_token_hash')

    if _column_exists('refresh_tokens', 'family_id'):
        op.drop_column('refresh_tokens', 'family_id')
