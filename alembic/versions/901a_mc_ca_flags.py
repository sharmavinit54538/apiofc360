"""Add maker_checker_enforced and needs_ca_validation flags to statutory_compliance_configs.

Revision ID: 901a_maker_checker_ca_validation_flags
Revises: d4e5f6a7b8c9
Create Date: 2026-10-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '901a_mc_ca_flags'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add maker_checker_enforced flag (default true)
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('payroll_maker_checker_enforced', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )

    # Add needs_ca_validation flags for all statutory components
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_pf_rates', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_esi_rates', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_pt_slabs', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_tds_slabs', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_gratuity', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_lwf', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'statutory_compliance_configs',
        sa.Column('needs_ca_validation_labour_codes', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )


def downgrade() -> None:
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_labour_codes')
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_lwf')
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_gratuity')
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_tds_slabs')
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_pt_slabs')
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_esi_rates')
    op.drop_column('statutory_compliance_configs', 'needs_ca_validation_pf_rates')
    op.drop_column('statutory_compliance_configs', 'payroll_maker_checker_enforced')