"""Add payroll tables manually

Revision ID: ccb36a901b6d
Revises: 333c09fabc83
Create Date: 2026-07-05 11:19:30.855182

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccb36a901b6d'
down_revision: Union[str, None] = '333c09fabc83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. statutory_compliance_configs
    op.create_table(
        'statutory_compliance_configs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('pf_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('employee_pf_rate', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('employer_pf_rate', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('pf_wage_ceiling', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('pf_on_full_basic', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('esi_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('employee_esi_rate', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('employer_esi_rate', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('esi_wage_ceiling', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('pt_state', sa.String(length=50), server_default='TELANGANA', nullable=False),
        sa.Column('pt_slabs', sa.JSON(), nullable=False),
        sa.Column('default_tax_regime', sa.String(length=10), server_default='NEW', nullable=False),
        sa.Column('lop_basis', sa.String(length=20), server_default='CALENDAR_DAYS', nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_statutory_configs_company_id', 'statutory_compliance_configs', ['company_id'], unique=False)

    # 2. salary_structures
    op.create_table(
        'salary_structures',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('annual_ctc', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('basic_monthly', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('hra_monthly', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('conveyance_monthly', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('special_allowance_monthly', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('other_allowances', sa.JSON(), nullable=True),
        sa.Column('annual_bonus', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('is_metro_city', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('rent_paid_monthly', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('tax_regime', sa.String(length=10), server_default='NEW', nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_salary_structures_company_id', 'salary_structures', ['company_id'], unique=False)
    op.create_index('ix_salary_structures_employee_id', 'salary_structures', ['employee_id'], unique=False)

    # 3. payroll_runs
    op.create_table(
        'payroll_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('total_employees', sa.Integer(), nullable=False),
        sa.Column('total_gross', sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column('total_deductions', sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column('total_net', sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column('run_by', sa.UUID(), nullable=True),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remarks', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'period_month', 'period_year', name='uq_payroll_run_company_period')
    )
    op.create_index('ix_payroll_runs_company_id', 'payroll_runs', ['company_id'], unique=False)

    # 4. payslips
    op.create_table(
        'payslips',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('payroll_run_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('salary_structure_id', sa.UUID(), nullable=True),
        sa.Column('payslip_number', sa.String(length=30), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('total_days_in_month', sa.Integer(), nullable=False),
        sa.Column('paid_days', sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column('lop_days', sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column('basic', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('hra', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('conveyance', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('special_allowance', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('other_allowances_total', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('arrears', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('bonus', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('lop_deduction', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('gross_earnings', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('employee_pf', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('employer_pf', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('employee_esi', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('employer_esi', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('professional_tax', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('tds', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('other_deductions', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('total_deductions', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('net_pay', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('net_pay_words', sa.String(length=500), nullable=True),
        sa.Column('payment_status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=True),
        sa.Column('payment_reference', sa.String(length=100), nullable=True),
        sa.Column('pdf_path', sa.String(length=500), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['salary_structure_id'], ['salary_structures.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'period_month', 'period_year', name='uq_payslip_employee_period'),
        sa.UniqueConstraint('payslip_number')
    )
    op.create_index('ix_payslips_company_id', 'payslips', ['company_id'], unique=False)
    op.create_index('ix_payslips_employee_id', 'payslips', ['employee_id'], unique=False)
    op.create_index('ix_payslips_payroll_run_id', 'payslips', ['payroll_run_id'], unique=False)

    # 5. payroll_attendance_inputs
    op.create_table(
        'payroll_attendance_inputs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('paid_days', sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column('lop_days', sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column('arrears', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('one_time_bonus', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('remarks', sa.String(length=255), nullable=True),
        sa.Column('entered_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entered_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'period_month', 'period_year', name='uq_attendance_employee_period')
    )
    op.create_index('ix_attendance_inputs_company_period', 'payroll_attendance_inputs', ['company_id', 'period_year', 'period_month'], unique=False)

    # 6. employee_investment_declarations
    op.create_table(
        'employee_investment_declarations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('financial_year', sa.String(length=9), nullable=False),
        sa.Column('section_80c', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('section_80d', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('section_80ccd1b_nps', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('home_loan_interest_24b', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('other_deductions', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('verified_by_hr', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'financial_year', name='uq_declaration_employee_fy')
    )


def downgrade() -> None:
    op.drop_table('employee_investment_declarations')
    op.drop_index('ix_attendance_inputs_company_period', table_name='payroll_attendance_inputs')
    op.drop_table('payroll_attendance_inputs')
    op.drop_index('ix_payslips_payroll_run_id', table_name='payslips')
    op.drop_index('ix_payslips_employee_id', table_name='payslips')
    op.drop_index('ix_payslips_company_id', table_name='payslips')
    op.drop_table('payslips')
    op.drop_index('ix_payroll_runs_company_id', table_name='payroll_runs')
    op.drop_table('payroll_runs')
    op.drop_index('ix_salary_structures_employee_id', table_name='salary_structures')
    op.drop_index('ix_salary_structures_company_id', table_name='salary_structures')
    op.drop_table('salary_structures')
    op.drop_index('ix_statutory_configs_company_id', table_name='statutory_compliance_configs')
    op.drop_table('statutory_compliance_configs')
