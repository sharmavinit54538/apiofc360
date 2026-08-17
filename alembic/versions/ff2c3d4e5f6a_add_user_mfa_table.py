"""add user_mfa table for TOTP multi-factor authentication

Revision ID: ff2c3d4e5f6a
Revises: ff1c2d3e4f5c
Create Date: 2026-08-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ff2c3d4e5f6a'
down_revision: Union[str, None] = 'ff1c2d3e4f5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "user_mfa" not in tables:
        op.create_table(
            'user_mfa',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
            sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('mfa_secret', sa.String(length=255), nullable=True),
            sa.Column('method', sa.String(length=50), nullable=False, server_default=sa.text("'totp'")),
            sa.Column('backup_codes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_user_mfa_user_id', 'user_mfa', ['user_id'], unique=True)
        op.create_index('ix_user_mfa_company_id', 'user_mfa', ['company_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "user_mfa" in tables:
        op.drop_index('ix_user_mfa_company_id', table_name='user_mfa')
        op.drop_index('ix_user_mfa_user_id', table_name='user_mfa')
        op.drop_table('user_mfa')
