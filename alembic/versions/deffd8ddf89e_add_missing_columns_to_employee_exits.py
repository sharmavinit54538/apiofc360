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
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("employee_exits")
    }
    cols_to_add = [
        ("notice_period_days_required", sa.Column("notice_period_days_required", sa.Integer(), nullable=False, server_default=sa.text("30"))),
        ("notice_period_days_served", sa.Column("notice_period_days_served", sa.Integer(), nullable=False, server_default=sa.text("0"))),
        ("notice_shortfall_days", sa.Column("notice_shortfall_days", sa.Integer(), nullable=False, server_default=sa.text("0"))),
        ("notice_buyout", sa.Column("notice_buyout", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
        ("notice_waived", sa.Column("notice_waived", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
        ("unpaid_salary_days", sa.Column("unpaid_salary_days", sa.Numeric(6, 2), nullable=True)),
        ("fnf_status", sa.Column("fnf_status", sa.String(30), nullable=False, server_default=sa.text("'PENDING'"))),
    ]
    for col_name, col in cols_to_add:
        if col_name not in existing_cols:
            op.add_column("employee_exits", col)


def downgrade() -> None:
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("employee_exits")
    }
    for col_name in (
        "fnf_status",
        "unpaid_salary_days",
        "notice_waived",
        "notice_buyout",
        "notice_shortfall_days",
        "notice_period_days_served",
        "notice_period_days_required",
    ):
        if col_name in existing_cols:
            op.drop_column("employee_exits", col_name)