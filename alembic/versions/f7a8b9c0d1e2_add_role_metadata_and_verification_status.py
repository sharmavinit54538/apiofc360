"""Add role_metadata JSONB and verification_status columns to employees.

Revision ID: f7a8b9c0d1e2
Revises: e30c63ba2146
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f7a8b9c0d1e2"
down_revision = "e30c63ba2146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "role_metadata",
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "verification_status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'PENDING_ADMIN_CREATED'"),
        ),
    )
    op.create_index(
        "ix_employees_verification_status",
        "employees",
        ["verification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_employees_verification_status", table_name="employees")
    op.drop_column("employees", "verification_status")
    op.drop_column("employees", "role_metadata")
