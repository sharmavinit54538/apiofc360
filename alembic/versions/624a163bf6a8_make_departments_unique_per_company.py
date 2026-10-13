"""make_departments_unique_per_company

Revision ID: 624a163bf6a8
Revises: 614ffa57eedf
Create Date: 2026-07-02 18:22:30.969123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Import idempotent helpers
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from helpers import safe_drop_index, safe_create_index

# revision identifiers, used by Alembic.
revision: str = '624a163bf6a8'
down_revision: Union[str, None] = '614ffa57eedf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing global unique indices (idempotent)
    safe_drop_index('ix_departments_department_code', 'departments')
    safe_drop_index('ix_departments_department_name', 'departments')

    # Create composite unique indices (unique per company)
    safe_create_index('ix_departments_department_code', 'departments', ['department_code', 'company_id'], unique=True)
    safe_create_index('ix_departments_department_name', 'departments', ['department_name', 'company_id'], unique=True)


def downgrade() -> None:
    # Drop composite unique indices (idempotent)
    safe_drop_index('ix_departments_department_code', 'departments')
    safe_drop_index('ix_departments_department_name', 'departments')

    # Recreate global unique indices (idempotent)
    safe_create_index('ix_departments_department_code', 'departments', ['department_code'], unique=True)
    safe_create_index('ix_departments_department_name', 'departments', ['department_name'], unique=True)
