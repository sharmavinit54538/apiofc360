"""Repair account_status and email_verified_at for already-verified users.

Revision ID: a7c91f2e4d03
Revises: 5f86290b9c11
Create Date: 2026-11-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a7c91f2e4d03"
down_revision = "5f86290b9c11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ensure verified users never remain stuck in PENDING_EMAIL_VERIFICATION."""
    op.execute(
        sa.text(
            """
            UPDATE users
            SET
                account_status = 'ACTIVE',
                is_active = TRUE,
                email_verified_at = COALESCE(email_verified_at, updated_at, created_at, NOW()),
                email_verification_token = NULL,
                email_verification_expires_at = NULL
            WHERE is_verified = TRUE
              AND UPPER(COALESCE(account_status, '')) = 'PENDING_EMAIL_VERIFICATION';
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET email_verified_at = COALESCE(updated_at, created_at, NOW())
            WHERE is_verified = TRUE
              AND email_verified_at IS NULL;
            """
        )
    )


def downgrade() -> None:
    """Data-repair migration; keep verified user accounts intact on downgrade."""
    pass
