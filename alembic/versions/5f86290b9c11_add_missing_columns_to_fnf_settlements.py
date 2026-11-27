"""Add missing columns to fnf_settlements for F&F tracking.

Revision ID: 5f86290b9c11
Revises: deffd8ddf89e
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "5f86290b9c11"
down_revision = "deffd8ddf89e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("fnf_settlements")
    }
    cols_to_add = [
        ("status", sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'DRAFT'"))),
        ("settlement_breakup", sa.Column("settlement_breakup", JSONB(), nullable=True)),
        ("statement_path", sa.Column("statement_path", sa.String(500), nullable=True)),
        ("statement_hash", sa.Column("statement_hash", sa.String(64), nullable=True)),
        ("settled_at", sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True)),
        ("generated_letters_json", sa.Column("generated_letters_json", JSONB(), nullable=True)),
    ]
    for col_name, col in cols_to_add:
        if col_name not in existing_cols:
            op.add_column("fnf_settlements", col)


def downgrade() -> None:
    bind = op.get_bind()
    existing_cols = {
        c["name"] for c in sa.inspect(bind).get_columns("fnf_settlements")
    }
    for col_name in (
        "generated_letters_json",
        "settled_at",
        "statement_hash",
        "statement_path",
        "settlement_breakup",
        "status",
    ):
        if col_name in existing_cols:
            op.drop_column("fnf_settlements", col_name)