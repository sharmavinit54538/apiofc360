"""make_departments_unique_per_company

Revision ID: 624a163bf6a8
Revises: 614ffa57eedf
Create Date: 2026-07-02 18:22:30.969123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '624a163bf6a8'
down_revision: Union[str, None] = '614ffa57eedf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing global unique indices
    op.drop_index('ix_departments_department_code', table_name='departments')
    op.drop_index('ix_departments_department_name', table_name='departments')

    # Create composite unique indices (unique per company)
    op.create_index('ix_departments_department_code', 'departments', ['department_code', 'company_id'], unique=True)
    op.create_index('ix_departments_department_name', 'departments', ['department_name', 'company_id'], unique=True)


def downgrade() -> None:
    # Drop composite unique indices
    op.drop_index('ix_departments_department_code', table_name='departments')
    op.drop_index('ix_departments_department_name', table_name='departments')

    # Recreate global unique indices
    op.create_index('ix_departments_department_code', 'departments', ['department_code'], unique=True)
    op.create_index('ix_departments_department_name', 'departments', ['department_name'], unique=True)
