"""merge_heads

Revision ID: 5570f8ae3daa
Revises: ('c5e3e22ccb2f', 'f9a8b7c6d5e4')
Create Date: 2026-07-21 15:11:52.226572

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5570f8ae3daa'
down_revision: Union[str, None] = ('c5e3e22ccb2f', 'f9a8b7c6d5e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
