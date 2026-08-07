"""add missing statutory config columns

Revision ID: fa0b9c8d7e6f
Revises: 5570f8ae3daa
Create Date: 2026-07-29 17:58:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa0b9c8d7e6f'
down_revision: Union[str, None] = '5570f8ae3daa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('statutory_compliance_configs', sa.Column('legal_business_name', sa.String(length=150), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('gst_number', sa.String(length=20), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('pan_number', sa.String(length=20), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('tan_number', sa.String(length=20), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('cin_number', sa.String(length=30), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('state', sa.String(length=50), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('working_days_policy', sa.String(length=50), nullable=True, server_default='EXCLUDE_WEEKENDS'))
    op.add_column('statutory_compliance_configs', sa.Column('salary_calc_method', sa.String(length=50), nullable=True, server_default='MONTHLY_FIXED'))
    op.add_column('statutory_compliance_configs', sa.Column('attendance_source', sa.String(length=50), nullable=True, server_default='FACE_BIOMETRIC'))
    op.add_column('statutory_compliance_configs', sa.Column('payslip_footer', sa.String(length=255), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('company_logo_url', sa.String(length=255), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('digital_signature_url', sa.String(length=255), nullable=True))
    op.add_column('statutory_compliance_configs', sa.Column('approval_levels', sa.Integer(), nullable=False, server_default='2'))


def downgrade() -> None:
    op.drop_column('statutory_compliance_configs', 'approval_levels')
    op.drop_column('statutory_compliance_configs', 'digital_signature_url')
    op.drop_column('statutory_compliance_configs', 'company_logo_url')
    op.drop_column('statutory_compliance_configs', 'payslip_footer')
    op.drop_column('statutory_compliance_configs', 'attendance_source')
    op.drop_column('statutory_compliance_configs', 'salary_calc_method')
    op.drop_column('statutory_compliance_configs', 'working_days_policy')
    op.drop_column('statutory_compliance_configs', 'state')
    op.drop_column('statutory_compliance_configs', 'cin_number')
    op.drop_column('statutory_compliance_configs', 'tan_number')
    op.drop_column('statutory_compliance_configs', 'pan_number')
    op.drop_column('statutory_compliance_configs', 'gst_number')
    op.drop_column('statutory_compliance_configs', 'legal_business_name')
