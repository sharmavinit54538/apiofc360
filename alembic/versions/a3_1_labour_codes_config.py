"""Add LabourCodesConfig table for Labour Codes (wages definition, 50% basic rule, gratuity/PF impact, fixed-term employment, overtime limits).

Revision ID: a3_1_labour_codes_config
Revises: 901a_mc_ca_flags
Create Date: 2026-10-27

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a3_1_labour_codes_config'
down_revision = '901a_mc_ca_flags'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'labour_codes_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        # 50% Basic Wage Rule (Code on Wages, 2019)
        sa.Column('basic_wage_min_pct', sa.Numeric(5, 4), nullable=False, server_default=sa.text('0.50')),
        sa.Column('basic_wage_rule_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('basic_wage_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_basic_wage', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # New Wages Definition (Code on Wages, 2019)
        sa.Column('wages_inclusions', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('wages_exclusions', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('wages_definition_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_wages_definition', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # Gratuity Impact (Code on Social Security, 2020)
        sa.Column('gratuity_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('gratuity_eligible_service_years', sa.Integer(), nullable=False, server_default=sa.text('5')),
        sa.Column('gratuity_calculation_base', sa.String(30), nullable=False, server_default=sa.text("'LAST_DRAWN_WAGES'")),
        sa.Column('gratuity_max_limit', sa.Numeric(14, 2), nullable=True),
        sa.Column('gratuity_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_gratuity', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # PF Impact (Code on Social Security, 2020)
        sa.Column('pf_on_wages_definition', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('pf_wage_ceiling_labour_codes', sa.Numeric(14, 2), nullable=True),
        sa.Column('pf_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_pf_labour_codes', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # Fixed-Term Employment (Industrial Relations Code, 2020)
        sa.Column('fixed_term_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('fixed_term_max_duration_months', sa.Integer(), nullable=False, server_default=sa.text('24')),
        sa.Column('fixed_term_renewal_allowed', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('fixed_term_gratuity_pro_rata', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('fixed_term_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_fixed_term', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # Overtime Limits (Code on Occupational Safety, 2020)
        sa.Column('overtime_max_hours_per_quarter', sa.Integer(), nullable=False, server_default=sa.text('125')),
        sa.Column('overtime_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_overtime', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # Night Shift & Spread Over (Code on Occupational Safety, 2020)
        sa.Column('spread_over_max_hours', sa.Integer(), nullable=False, server_default=sa.text('12')),
        sa.Column('night_shift_allowance_pct', sa.Numeric(5, 4), nullable=True),
        sa.Column('night_shift_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_night_shift', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        # Leave & Holiday Rules (Code on Social Security, 2020)
        sa.Column('earned_leave_per_year', sa.Integer(), nullable=False, server_default=sa.text('15')),
        sa.Column('sick_leave_per_year', sa.Integer(), nullable=False, server_default=sa.text('12')),
        sa.Column('casual_leave_per_year', sa.Integer(), nullable=False, server_default=sa.text('12')),
        sa.Column('maternity_leave_weeks', sa.Integer(), nullable=False, server_default=sa.text('26')),
        sa.Column('paternity_leave_days', sa.Integer(), nullable=False, server_default=sa.text('15')),
        sa.Column('leave_source_note', sa.String(500), nullable=True),
        sa.Column('needs_ca_validation_leave', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('settings_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('effective_from', sa.Date(), nullable=False, server_default=sa.text('CURRENT_DATE')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), onupdate=sa.text('now()')),
    )
    op.create_index('ix_labour_codes_configs_company_id', 'labour_codes_configs', ['company_id'], unique=False)
    op.create_index('ix_labour_codes_configs_effective_from', 'labour_codes_configs', ['effective_from'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_labour_codes_configs_effective_from', table_name='labour_codes_configs')
    op.drop_index('ix_labour_codes_configs_company_id', table_name='labour_codes_configs')
    op.drop_table('labour_codes_configs')