"""Add deactivation columns to employees.

Revision ID: 8b7c6d5e4f3a
Revises: f7a8b9c0d1e2
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "8b7c6d5e4f3a"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "deactivated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "deactivated_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "employees",
        sa.Column(
            "deactivation_reason",
            sa.String(length=1000),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("employees", "deactivation_reason")
    op.drop_column("employees", "deactivated_by")
    op.drop_column("employees", "deactivated_at")
    op.drop_column("employees", "is_active")
