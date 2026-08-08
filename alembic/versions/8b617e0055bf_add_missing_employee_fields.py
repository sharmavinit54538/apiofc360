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
    # Personal information fields
    op.add_column('employees', sa.Column('middle_name', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('father_name', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('mother_name', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('spouse_name', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('nationality', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('preferred_language', sa.String(length=50), nullable=True))
    op.add_column('employees', sa.Column('aadhaar_number', sa.String(length=20), nullable=True))
    op.add_column('employees', sa.Column('passport_number', sa.String(length=20), nullable=True))
    op.add_column('employees', sa.Column('driving_license', sa.String(length=30), nullable=True))
    op.add_column('employees', sa.Column('voter_id', sa.String(length=20), nullable=True))
    op.add_column('employees', sa.Column('tax_regime', sa.String(length=20), nullable=True))
    op.add_column('employees', sa.Column('upi_id', sa.String(length=50), nullable=True))
    
    # ESI number - note: different from esi_number (statutory)
    op.add_column('employees', sa.Column('esic_number', sa.String(length=30), nullable=True))
    
    # Work and employment details
    op.add_column('employees', sa.Column('work_mode', sa.String(length=30), nullable=True))
    op.add_column('employees', sa.Column('business_unit', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('employee_category', sa.String(length=50), nullable=True))
    op.add_column('employees', sa.Column('probation_period_months', sa.Integer(), nullable=True))
    
    # Onboarding fields
    op.add_column('employees', sa.Column('onboarding_data', sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column('employees', sa.Column('employee_onboarding_completed', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('employees', sa.Column('employee_onboarding_step', sa.Integer(), nullable=False, server_default=sa.text('1')))
    
    # Cost center
    op.add_column('employees', sa.Column('cost_center_id', sa.String(length=100), nullable=True))


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