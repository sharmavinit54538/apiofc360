"""add account_status and verification fields to users

Revision ID: fe1c2d3e4f5b
Revises: fd2e3f4a5b6c
Create Date: 2026-08-14 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fe1c2d3e4f5b'
down_revision: Union[str, None] = 'fd2e3f4a5b6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add account_status column if not exists
    has_account_status = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='account_status'"
    )).scalar()
    if not has_account_status:
        op.add_column(
            'users',
            sa.Column(
                'account_status',
                sa.String(50),
                nullable=False,
                server_default=sa.text("'PENDING_EMAIL_VERIFICATION'"),
            ),
        )

    # 2. Add email_verification_token column if not exists
    has_token = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='email_verification_token'"
    )).scalar()
    if not has_token:
        op.add_column(
            'users',
            sa.Column('email_verification_token', sa.String(255), nullable=True),
        )

    # 3. Add email_verification_expires_at column if not exists
    has_expires = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='email_verification_expires_at'"
    )).scalar()
    if not has_expires:
        op.add_column(
            'users',
            sa.Column('email_verification_expires_at', sa.DateTime(timezone=True), nullable=True),
        )

    # 4. Add created_by column if not exists
    has_created_by = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='created_by'"
    )).scalar()
    if not has_created_by:
        op.add_column(
            'users',
            sa.Column(
                'created_by',
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey('users.id', ondelete='SET NULL'),
                nullable=True,
            ),
        )

    # 5. Backfill account_status for existing users based on is_active & is_verified
    op.execute("""
        UPDATE users
        SET account_status = CASE
            WHEN is_active = TRUE AND is_verified = TRUE THEN 'ACTIVE'
            WHEN is_active = FALSE AND is_verified = TRUE THEN 'SUSPENDED'
            ELSE 'PENDING_EMAIL_VERIFICATION'
        END
        WHERE account_status IS NULL OR account_status = 'PENDING_EMAIL_VERIFICATION';
    """)


def downgrade() -> None:
    op.drop_column('users', 'created_by')
    op.drop_column('users', 'email_verification_expires_at')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'account_status')
