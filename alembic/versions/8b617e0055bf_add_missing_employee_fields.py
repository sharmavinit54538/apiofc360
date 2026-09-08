"""add_missing_employee_fields

Revision ID: 8b617e0055bf
Revises: fa0b9c8d7e6f
Create Date: 2026-08-08 18:43:05.429149

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '8b617e0055bf'
down_revision: Union[str, None] = 'fa0b9c8d7e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing employee fields to match SQLAlchemy model."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    emp_cols = [c['name'] for c in inspector.get_columns('employees')]

    cols = [
        ('middle_name', sa.String(length=100), None, True),
        ('father_name', sa.String(length=100), None, True),
        ('mother_name', sa.String(length=100), None, True),
        ('spouse_name', sa.String(length=100), None, True),
        ('nationality', sa.String(length=100), None, True),
        ('preferred_language', sa.String(length=50), None, True),
        ('aadhaar_number', sa.String(length=20), None, True),
        ('passport_number', sa.String(length=20), None, True),
        ('driving_license', sa.String(length=30), None, True),
        ('voter_id', sa.String(length=20), None, True),
        ('tax_regime', sa.String(length=20), None, True),
        ('upi_id', sa.String(length=50), None, True),
        ('esic_number', sa.String(length=30), None, True),
        ('work_mode', sa.String(length=30), None, True),
        ('business_unit', sa.String(length=100), None, True),
        ('employee_category', sa.String(length=50), None, True),
        ('probation_period_months', sa.Integer(), None, True),
        ('onboarding_data', sa.dialects.postgresql.JSONB(), None, True),
        ('employee_onboarding_completed', sa.Boolean(), sa.text('false'), False),
        ('employee_onboarding_step', sa.Integer(), sa.text('1'), False),
        ('cost_center_id', sa.String(length=100), None, True),
    ]

    for col_name, col_type, default_val, is_nullable in cols:
        if col_name not in emp_cols:
            op.add_column('employees', sa.Column(col_name, col_type, nullable=is_nullable, server_default=default_val))


def downgrade() -> None:
    op.drop_column('employees', 'cost_center_id')
    op.drop_column('employees', 'employee_onboarding_step')
    op.drop_column('employees', 'employee_onboarding_completed')
    op.drop_column('employees', 'onboarding_data')
    op.drop_column('employees', 'probation_period_months')
    op.drop_column('employees', 'employee_category')
    op.drop_column('employees', 'business_unit')
    op.drop_column('employees', 'work_mode')
    op.drop_column('employees', 'esic_number')
    op.drop_column('employees', 'upi_id')
    op.drop_column('employees', 'tax_regime')
    op.drop_column('employees', 'voter_id')
    op.drop_column('employees', 'driving_license')
    op.drop_column('employees', 'passport_number')
    op.drop_column('employees', 'aadhaar_number')
    op.drop_column('employees', 'preferred_language')
    op.drop_column('employees', 'nationality')
    op.drop_column('employees', 'spouse_name')
    op.drop_column('employees', 'mother_name')
    op.drop_column('employees', 'father_name')
    op.drop_column('employees', 'middle_name')