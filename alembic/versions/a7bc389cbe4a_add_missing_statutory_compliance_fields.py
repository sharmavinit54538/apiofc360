"""add_missing_statutory_compliance_fields

Revision ID: a7bc389cbe4a
Revises: ece532a97168
Create Date: 2026-08-08 19:10:46.654322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7bc389cbe4a'
down_revision: Union[str, None] = 'ece532a97168'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
