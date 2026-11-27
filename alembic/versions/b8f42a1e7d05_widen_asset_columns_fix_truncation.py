"""Widen asset table columns to fix StringDataRightTruncationError.

Revision ID: b8f42a1e7d05
Revises: a7c91f2e4d03
Create Date: 2026-11-27 07:50:00.000000

Columns changed (all widened, never narrowed):
- name: VARCHAR(150) -> VARCHAR(255)
- category: VARCHAR(50) -> VARCHAR(100)
- serial: VARCHAR(100) -> VARCHAR(150)
- vendor: VARCHAR(100) -> VARCHAR(255)
- status: VARCHAR(30) -> VARCHAR(50)
- brand: VARCHAR(100) -> VARCHAR(150)
- model: VARCHAR(100) -> VARCHAR(150)
- location: VARCHAR(100) -> TEXT
- image_url: VARCHAR(255) -> TEXT

Already correct (no change):
- tag: VARCHAR(100) - unchanged
- notes: TEXT - unchanged
- description: TEXT - unchanged
- lost_reason: TEXT - unchanged
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8f42a1e7d05"
down_revision = "a7c91f2e4d03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Widen asset columns to match business requirements.
    
    All changes widen columns (never narrow), so existing data is preserved.
    ALTER TYPE operations are non-destructive for VARCHAR -> wider VARCHAR or TEXT.
    """
    # name: VARCHAR(150) -> VARCHAR(255)
    op.alter_column(
        "assets", "name",
        existing_type=sa.String(150),
        type_=sa.String(255),
        existing_nullable=False,
    )
    # category: VARCHAR(50) -> VARCHAR(100)
    op.alter_column(
        "assets", "category",
        existing_type=sa.String(50),
        type_=sa.String(100),
        existing_nullable=False,
    )
    # serial: VARCHAR(100) -> VARCHAR(150)
    op.alter_column(
        "assets", "serial",
        existing_type=sa.String(100),
        type_=sa.String(150),
        existing_nullable=True,
    )
    # vendor: VARCHAR(100) -> VARCHAR(255)
    op.alter_column(
        "assets", "vendor",
        existing_type=sa.String(100),
        type_=sa.String(255),
        existing_nullable=True,
    )
    # status: VARCHAR(30) -> VARCHAR(50)
    op.alter_column(
        "assets", "status",
        existing_type=sa.String(30),
        type_=sa.String(50),
        existing_nullable=False,
    )
    # brand: VARCHAR(100) -> VARCHAR(150)
    op.alter_column(
        "assets", "brand",
        existing_type=sa.String(100),
        type_=sa.String(150),
        existing_nullable=True,
    )
    # model: VARCHAR(100) -> VARCHAR(150)
    op.alter_column(
        "assets", "model",
        existing_type=sa.String(100),
        type_=sa.String(150),
        existing_nullable=True,
    )
    # location: VARCHAR(100) -> TEXT
    op.alter_column(
        "assets", "location",
        existing_type=sa.String(100),
        type_=sa.Text(),
        existing_nullable=True,
    )
    # image_url: VARCHAR(255) -> TEXT  (root cause of StringDataRightTruncationError)
    op.alter_column(
        "assets", "image_url",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Revert column widths.
    
    WARNING: Downgrade may cause data truncation if existing data exceeds
    the original column limits. This is documented but not prevented because
    the original limits were too restrictive.
    """
    op.alter_column(
        "assets", "image_url",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=True,
    )
    op.alter_column(
        "assets", "location",
        existing_type=sa.Text(),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "assets", "model",
        existing_type=sa.String(150),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "assets", "brand",
        existing_type=sa.String(150),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "assets", "status",
        existing_type=sa.String(50),
        type_=sa.String(30),
        existing_nullable=False,
    )
    op.alter_column(
        "assets", "vendor",
        existing_type=sa.String(255),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "assets", "serial",
        existing_type=sa.String(150),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "assets", "category",
        existing_type=sa.String(100),
        type_=sa.String(50),
        existing_nullable=False,
    )
    op.alter_column(
        "assets", "name",
        existing_type=sa.String(255),
        type_=sa.String(150),
        existing_nullable=False,
    )
