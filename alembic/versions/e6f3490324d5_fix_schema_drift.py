"""fix_schema_drift

Revision ID: e6f3490324d5
Revises: 21cb61c4b06d
Create Date: 2026-07-02 13:45:10.327638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f3490324d5'
down_revision: Union[str, None] = '21cb61c4b06d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Add missing columns to 'users' table
    user_cols = {c['name'] for c in insp.get_columns('users')} if insp.has_table('users') else set()
    if 'failed_login_attempts' not in user_cols:
        op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False))
    if 'locked_until' not in user_cols:
        op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    if 'token_version' not in user_cols:
        op.add_column('users', sa.Column('token_version', sa.Integer(), server_default=sa.text('1'), nullable=False))

    # 2. Add missing column 'revoked_at' to 'refresh_tokens' table
    rt_cols = {c['name'] for c in insp.get_columns('refresh_tokens')} if insp.has_table('refresh_tokens') else set()
    if 'revoked_at' not in rt_cols:
        op.add_column('refresh_tokens', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))

    # 3. Create missing 'audit_logs' table
    if not insp.has_table('audit_logs'):
        op.create_table(
            'audit_logs',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=True),
            sa.Column('action', sa.String(length=100), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('ip_address', sa.String(length=45), nullable=True),
            sa.Column('user_agent', sa.String(length=255), nullable=True),
            sa.Column('details', sa.String(length=1000), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_logs_user_id_users'), ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Drop 'audit_logs' table
    if insp.has_table('audit_logs'):
        op.drop_table('audit_logs')

    # 2. Drop 'revoked_at' column from 'refresh_tokens' table
    rt_cols = {c['name'] for c in insp.get_columns('refresh_tokens')} if insp.has_table('refresh_tokens') else set()
    if 'revoked_at' in rt_cols:
        op.drop_column('refresh_tokens', 'revoked_at')

    # 3. Drop columns from 'users' table
    user_cols = {c['name'] for c in insp.get_columns('users')} if insp.has_table('users') else set()
    if 'token_version' in user_cols:
        op.drop_column('users', 'token_version')
    if 'locked_until' in user_cols:
        op.drop_column('users', 'locked_until')
    if 'failed_login_attempts' in user_cols:
        op.drop_column('users', 'failed_login_attempts')

