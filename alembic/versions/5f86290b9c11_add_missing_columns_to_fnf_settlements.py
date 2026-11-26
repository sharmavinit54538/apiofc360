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
    # Add missing columns that don't exist yet
    op.add_column(
        "fnf_settlements",
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'DRAFT'")),
    )
    op.add_column(
        "fnf_settlements",
        sa.Column("settlement_breakup", JSONB(), nullable=True),
    )
    op.add_column(
        "fnf_settlements",
        sa.Column("statement_path", sa.String(500), nullable=True),
    )
    op.add_column(
        "fnf_settlements",
        sa.Column("statement_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "fnf_settlements",
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "fnf_settlements",
        sa.Column("generated_letters_json", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fnf_settlements", "generated_letters_json")
    op.drop_column("fnf_settlements", "settled_at")
    op.drop_column("fnf_settlements", "statement_hash")
    op.drop_column("fnf_settlements", "statement_path")
    op.drop_column("fnf_settlements", "settlement_breakup")
    op.drop_column("fnf_settlements", "status")