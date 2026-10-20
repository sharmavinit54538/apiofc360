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
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Add message_metadata to ai_messages if not exists
    existing_ai_cols = {c['name'] for c in insp.get_columns('ai_messages')}
    if 'message_metadata' not in existing_ai_cols:
        op.add_column(
            'ai_messages',
            sa.Column('message_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )

    # 2. Safely sanitize any orphaned locked_by references before adding foreign key constraint
    # (locked_by is nullable with ondelete='SET NULL')
    # Resolve inconsistent data safely: only sets invalid references to NULL, never deletes users or payroll records.
    op.execute("""
        UPDATE payroll_periods
        SET locked_by = NULL
        WHERE locked_by IS NOT NULL
          AND locked_by NOT IN (SELECT id FROM users)
    """)

    # 3. Add foreign key constraint linking payroll_periods.locked_by to users.id if not exists
    existing_fks = {fk['name'] for fk in insp.get_foreign_keys('payroll_periods')}
    if 'fk_payroll_periods_locked_by_users' not in existing_fks:
        op.create_foreign_key(
            'fk_payroll_periods_locked_by_users',
            'payroll_periods',
            'users',
            ['locked_by'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Drop foreign key constraint if exists
    existing_fks = {fk['name'] for fk in insp.get_foreign_keys('payroll_periods')}
    if 'fk_payroll_periods_locked_by_users' in existing_fks:
        op.drop_constraint('fk_payroll_periods_locked_by_users', 'payroll_periods', type_='foreignkey')

    # 2. Drop message_metadata column if exists
    existing_ai_cols = {c['name'] for c in insp.get_columns('ai_messages')}
    if 'message_metadata' in existing_ai_cols:
        op.drop_column('ai_messages', 'message_metadata')

