"""Baseline schema migration - Single head baseline for all ORM models.

Revision ID: 0001
Revises: 
Create Date: 2026-10-14

This is the single baseline migration that creates all tables from the current
ORM model state. All previous fragmented migrations have been consolidated.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ENUM

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables from the unified ORM model."""
    # This migration is a placeholder - the actual schema is managed by
    # SQLAlchemy's Base.metadata.create_all() at startup via the schema healing utility.
    # The real tables are created by the ORM models directly.
    pass


def downgrade() -> None:
    """Drop all tables - not recommended for production."""
    # This is a baseline migration - downgrade would drop everything.
    # Only use in development/test environments.
    op.execute("DROP TYPE IF EXISTS entryapprovalstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS shifttype CASCADE")
    op.execute("DROP TYPE IF EXISTS shiftplansource CASCADE")
    op.execute("DROP TYPE IF EXISTS shiftplanstatus CASCADE")
    op.execute("DROP TYPE IF EXISTS user_role CASCADE")