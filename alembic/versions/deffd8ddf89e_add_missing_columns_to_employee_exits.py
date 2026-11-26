"""Add missing notice period and F&F columns to employee_exits.

Revision ID: deffd8ddf89e
Revises: 1e80eec1f209
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "deffd8ddf89e"
down_revision = "1e80eec1f209"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add missing notice period columns
    op.add_column(
        "employee_exits",
        sa.Column("notice_period_days_required", sa.Integer(), nullable=False, server_default=sa.text("30")),
    )
    op.add_column(
        "employee_exits",
        sa.Column("notice_period_days_served", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "employee_exits",
        sa.Column("notice_shortfall_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "employee_exits",
        sa.Column("notice_buyout", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "employee_exits",
        sa.Column("notice_waived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "employee_exits",
        sa.Column("unpaid_salary_days", sa.Numeric(6, 2), nullable=True),
    )
    op.add_column(
        "employee_exits",
        sa.Column("fnf_status", sa.String(30), nullable=False, server_default=sa.text("'PENDING'")),
    )


def downgrade() -> None:
    op.drop_column("employee_exits", "fnf_status")
    op.drop_column("employee_exits", "unpaid_salary_days")
    op.drop_column("employee_exits", "notice_waived")
    op.drop_column("employee_exits", "notice_buyout")
    op.drop_column("employee_exits", "notice_shortfall_days")
    op.drop_column("employee_exits", "notice_period_days_served")
    op.drop_column("employee_exits", "notice_period_days_required")