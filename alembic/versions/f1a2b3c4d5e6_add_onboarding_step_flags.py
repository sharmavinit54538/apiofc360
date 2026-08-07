"""Add per-step completion flags to onboarding_progress table.

Revision ID: f1a2b3c4d5e6
Revises: e6f3490324d5
Create Date: 2026-07-06 13:20:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "ac8e82e5d254"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 7 boolean step-completion flags and ensure current_step has server_default."""
    op.add_column(
        "onboarding_progress",
        sa.Column("company_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "onboarding_progress",
        sa.Column("admin_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "onboarding_progress",
        sa.Column("hr_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "onboarding_progress",
        sa.Column("departments_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "onboarding_progress",
        sa.Column("designations_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "onboarding_progress",
        sa.Column("employees_invited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "onboarding_progress",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Ensure any existing rows (companies already partially onboarded) have their
    # flags backfilled from the company.onboarding_step integer so they don't lose progress.
    op.execute(
        """
        UPDATE onboarding_progress op
        SET
            company_completed      = (c.onboarding_step >= 2),
            admin_completed        = (c.onboarding_step >= 3),
            hr_completed           = (c.onboarding_step >= 4),
            departments_completed  = (c.onboarding_step >= 5),
            designations_completed = (c.onboarding_step >= 5),
            employees_invited      = (c.onboarding_step >= 6),
            onboarding_completed   = c.onboarding_completed,
            current_step           = c.onboarding_step
        FROM companies c
        WHERE op.company_id = c.id
        """
    )


def downgrade() -> None:
    """Remove the 7 step-completion flag columns."""
    op.drop_column("onboarding_progress", "onboarding_completed")
    op.drop_column("onboarding_progress", "employees_invited")
    op.drop_column("onboarding_progress", "designations_completed")
    op.drop_column("onboarding_progress", "departments_completed")
    op.drop_column("onboarding_progress", "hr_completed")
    op.drop_column("onboarding_progress", "admin_completed")
    op.drop_column("onboarding_progress", "company_completed")
