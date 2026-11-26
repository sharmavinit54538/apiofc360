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
    # Add encashable columns for F&F leave encashment calculation
    op.add_column(
        "employee_leave_policies",
        sa.Column("encashable", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "employee_leave_policies",
        sa.Column("encashable_days", sa.Numeric(6, 1), nullable=True),
    )
    op.add_column(
        "employee_leave_policies",
        sa.Column("encashment_base", sa.String(10), nullable=False, server_default="BASIC"),
    )
    op.add_column(
        "employee_leave_policies",
        sa.Column("encashment_divisor", sa.Integer(), nullable=False, server_default="30"),
    )


def downgrade() -> None:
    op.drop_column("employee_leave_policies", "encashment_divisor")
    op.drop_column("employee_leave_policies", "encashment_base")
    op.drop_column("employee_leave_policies", "encashable_days")
    op.drop_column("employee_leave_policies", "encashable")