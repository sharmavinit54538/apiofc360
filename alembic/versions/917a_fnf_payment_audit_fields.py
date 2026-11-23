"""Add FNF payment audit fields

Revision ID: 917a
Revises: 916a
Create Date: 2026-11-16

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "917a"
down_revision = "916a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add payment audit fields to fnf_settlements
    op.add_column("fnf_settlements", sa.Column("payment_reference", sa.String(100), nullable=True))
    op.add_column("fnf_settlements", sa.Column("payment_utr", sa.String(100), nullable=True))
    op.add_column("fnf_settlements", sa.Column("payment_confirmed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("fnf_settlements", sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fnf_settlements", sa.Column("payment_remarks", sa.Text, nullable=True))
    
    # Create unique index on payment_reference
    op.create_index("ix_fnf_payment_reference", "fnf_settlements", ["payment_reference"], unique=True, postgresql_where=sa.text("payment_reference IS NOT NULL"))
    
    # Create index on payment_confirmed_by
    op.create_index("ix_fnf_payment_confirmed_by", "fnf_settlements", ["payment_confirmed_by"])


def downgrade() -> None:
    op.drop_index("ix_fnf_payment_confirmed_by", table_name="fnf_settlements")
    op.drop_index("ix_fnf_payment_reference", table_name="fnf_settlements")
    op.drop_column("fnf_settlements", "payment_remarks")
    op.drop_column("fnf_settlements", "payment_confirmed_at")
    op.drop_column("fnf_settlements", "payment_confirmed_by")
    op.drop_column("fnf_settlements", "payment_utr")
    op.drop_column("fnf_settlements", "payment_reference")