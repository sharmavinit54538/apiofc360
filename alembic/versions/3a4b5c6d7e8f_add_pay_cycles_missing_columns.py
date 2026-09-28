"""add pay_cycles missing columns and merge heads

Revision ID: 3a4b5c6d7e8f
Revises: 2a3b4c5d6e7f, ff2c3d4e5f6a
Create Date: 2026-08-20 12:00:00.000000

Non-destructive, idempotent migration that adds missing columns to pay_cycles table
to match SQLAlchemy PayCycle model and prevent UndefinedColumnError.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision: str = '3a4b5c6d7e8f'
down_revision: Union[str, Sequence[str], None] = ('2a3b4c5d6e7f', 'ff2c3d4e5f6a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'pay_cycles' in inspector.get_table_names():
        pay_cols = [c['name'] for c in inspector.get_columns('pay_cycles')]

        cols_to_add = [
            ('name', sa.String(100), sa.text("'Monthly Payroll Cycle'"), False),
            ('frequency', sa.String(30), sa.text("'MONTHLY'"), False),
            ('start_date', sa.Date(), None, True),
            ('end_date', sa.Date(), None, True),
            ('processing_date', sa.Date(), None, True),
            ('payment_date', sa.Date(), None, True),
            ('payslip_generation_date', sa.Date(), None, True),
            ('attendance_lock_date', sa.Date(), None, True),
            ('leave_lock_date', sa.Date(), None, True),
            ('overtime_lock_date', sa.Date(), None, True),
            ('tax_calculation_date', sa.Date(), None, True),
            ('bonus_processing_date', sa.Date(), None, True),
            ('is_active', sa.Boolean(), sa.text('false'), False),
            ('is_locked', sa.Boolean(), sa.text('false'), False),
            ('locks', postgresql.JSON(astext_type=sa.Text()), None, True),
            ('automation', postgresql.JSON(astext_type=sa.Text()), None, True),
        ]

        for col_name, col_type, default_val, is_nullable in cols_to_add:
            if col_name not in pay_cols:
                op.add_column(
                    'pay_cycles',
                    sa.Column(col_name, col_type, nullable=is_nullable, server_default=default_val)
                )


def downgrade() -> None:
    pass
