"""restore account lockout and failed login tracking fields on users table

Revision ID: 1a2b3c4d5e6f
Revises: ff1c2d3e4f5c
Create Date: 2026-08-15 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'ff1c2d3e4f5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Check if failed_login_attempts column exists
    result = conn.execute(sa.text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'failed_login_attempts'
    """)).scalar()

    if not result:
        op.add_column(
            'users',
            sa.Column('failed_login_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False)
        )

    # Check if locked_until column exists
    result_lock = conn.execute(sa.text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'locked_until'
    """)).scalar()

    if not result_lock:
        op.add_column(
            'users',
            sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'locked_until'
    """)).scalar()
    if result:
        op.drop_column('users', 'locked_until')

    result_failed = conn.execute(sa.text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'failed_login_attempts'
    """)).scalar()
    if result_failed:
        op.drop_column('users', 'failed_login_attempts')
