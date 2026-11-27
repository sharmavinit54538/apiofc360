"""Add encashable columns to employee_leave_policies for F&F leave encashment.

Revision ID: 1e80eec1f209
Revises: 17c1ab7c9e4d
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "1e80eec1f209"
down_revision = "17c1ab7c9e4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("employee_leave_policies")
    }
    cols_to_add = [
        ("encashable", sa.Column("encashable", sa.Boolean(), nullable=True)),
        ("encashable_days", sa.Column("encashable_days", sa.Numeric(6, 1), nullable=True)),
        ("encashment_base", sa.Column("encashment_base", sa.String(10), nullable=False, server_default="BASIC")),
        ("encashment_divisor", sa.Column("encashment_divisor", sa.Integer(), nullable=False, server_default="30")),
    ]
    for col_name, col in cols_to_add:
        if col_name not in existing_cols:
            op.add_column("employee_leave_policies", col)


def downgrade() -> None:
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("employee_leave_policies")
    }
    for col_name in ("encashment_divisor", "encashment_base", "encashable_days", "encashable"):
        if col_name in existing_cols:
            op.drop_column("employee_leave_policies", col_name)