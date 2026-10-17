"""Add ai_messages.message_metadata and payroll_periods.locked_by foreign key.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-10-17 06:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add message_metadata to ai_messages
    op.add_column(
        'ai_messages',
        sa.Column('message_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    # 2. Safely sanitize any orphaned locked_by references before adding foreign key constraint
    # (locked_by is nullable with ondelete='SET NULL')
    op.execute("""
        UPDATE payroll_periods
        SET locked_by = NULL
        WHERE locked_by IS NOT NULL
          AND locked_by NOT IN (SELECT id FROM users)
    """)

    # 3. Add foreign key constraint linking payroll_periods.locked_by to users.id
    op.create_foreign_key(
        'fk_payroll_periods_locked_by_users',
        'payroll_periods',
        'users',
        ['locked_by'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # 1. Drop foreign key constraint
    op.drop_constraint('fk_payroll_periods_locked_by_users', 'payroll_periods', type_='foreignkey')

    # 2. Drop message_metadata column
    op.drop_column('ai_messages', 'message_metadata')
