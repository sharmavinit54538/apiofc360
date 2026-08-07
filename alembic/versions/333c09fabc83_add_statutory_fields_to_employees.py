"""Add statutory fields to employees

Revision ID: 333c09fabc83
Revises: da4e07c0b748
Create Date: 2026-07-05 11:17:03.044815

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '333c09fabc83'
down_revision: Union[str, None] = 'da4e07c0b748'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('pan_number', sa.String(length=10), nullable=True))
    op.add_column('employees', sa.Column('uan_number', sa.String(length=12), nullable=True))
    op.add_column('employees', sa.Column('pf_number', sa.String(length=30), nullable=True))
    op.add_column('employees', sa.Column('esi_number', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('employees', 'esi_number')
    op.drop_column('employees', 'pf_number')
    op.drop_column('employees', 'uan_number')
    op.drop_column('employees', 'pan_number')
