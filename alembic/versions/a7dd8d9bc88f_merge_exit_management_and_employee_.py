"""Merge exit management and employee schema contract branches

Revision ID: a7dd8d9bc88f
Revises: ('41a_employee_schema_contract', '918a')
Create Date: 2026-11-16 13:08:33.115976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7dd8d9bc88f'
down_revision: Union[str, None] = ('41a_employee_schema_contract', '918a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
