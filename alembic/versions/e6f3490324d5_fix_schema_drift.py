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
    # 1. Add missing columns to 'users' table
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default=sa.text('1'), nullable=False))

    # 2. Add missing column 'revoked_at' to 'refresh_tokens' table
    op.add_column('refresh_tokens', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))

    # 3. Create missing 'audit_logs' table
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
    # 1. Drop 'audit_logs' table
    op.drop_table('audit_logs')

    # 2. Drop 'revoked_at' column from 'refresh_tokens' table
    op.drop_column('refresh_tokens', 'revoked_at')

    # 3. Drop columns from 'users' table
    op.drop_column('users', 'token_version')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')

