"""add employee invitation fields

Revision ID: 9449fdcd34d5
Revises: e589353e4605
Create Date: 2026-07-01 12:42:28.869316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9449fdcd34d5'
down_revision: Union[str, None] = 'e589353e4605'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("employees", sa.Column("invited_by", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("employees", "invited_by")
    op.drop_column("employees", "invited_at")
