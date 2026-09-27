"""create payroll v2 tables and columns

Revision ID: c1a2b3c4d5e6
Revises: b2c3d4e5f6a8
Create Date: 2026-09-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c1a2b3c4d5e6'
down_revision = 'b2c3d4e5f6a8'
branch_labels = None
depends_on = None


def upgrade():
    # 1. payroll_periods
    op.create_table(
        'payroll_periods',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('pay_date', sa.Date(), nullable=False),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='OPEN'),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_payroll_periods_company_id', 'payroll_periods', ['company_id'])
    op.create_index('ix_payroll_periods_dates', 'payroll_periods', ['start_date', 'end_date'])

    # 2. Add columns to payroll_runs if not exists
    run_cols = [
        sa.Column('period_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payroll_periods.id', ondelete='SET NULL'), nullable=True),
        sa.Column('run_number', sa.String(50), nullable=True),
        sa.Column('total_gross_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_deductions_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_net_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('validation_status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('validation_errors', sa.JSON(), nullable=True),
        sa.Column('validation_notes', sa.String(500), nullable=True),
        sa.Column('is_locked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('comments', sa.String(500), nullable=True),
        sa.Column('job_id', sa.String(100), nullable=True),
        sa.Column('finalized_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('sent_back_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('sent_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_back_reason', sa.String(500), nullable=True),
    ]
    for col in run_cols:
        try:
            op.add_column('payroll_runs', col)
        except Exception:
            pass

    # 3. payroll_run_employees
    op.create_table(
        'payroll_run_employees',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('gross_earnings_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_deductions_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('net_pay_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('paid_days', sa.Numeric(5, 1), nullable=False, server_default='30.0'),
        sa.Column('lop_days', sa.Numeric(5, 1), nullable=False, server_default='0.0'),
        sa.Column('validation_status', sa.String(30), nullable=False, server_default='VALID'),
        sa.Column('validation_messages', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('earnings_breakup', sa.JSON(), nullable=True),
        sa.Column('deductions_breakup', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('run_id', 'employee_id', name='uq_run_employee'),
    )
    op.create_index('ix_run_employees_run_id', 'payroll_run_employees', ['run_id'])
    op.create_index('ix_run_employees_employee_id', 'payroll_run_employees', ['employee_id'])
    op.create_index('ix_run_employees_company_id', 'payroll_run_employees', ['company_id'])

    # 4. pay_components
    op.create_table(
        'pay_components',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('taxable', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('statutory', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('calculation_method', sa.String(30), nullable=False, server_default='flat'),
        sa.Column('default_percentage', sa.Numeric(7, 4), nullable=True),
        sa.Column('formula_expr', sa.String(255), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_pay_components_company_id', 'pay_components', ['company_id'])
    op.create_index('ix_pay_components_code', 'pay_components', ['code'])

    # 5. compensations
    op.create_table(
        'compensations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('ctc_annual_paise', sa.BigInteger(), nullable=False),
        sa.Column('basic_monthly_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('hra_monthly_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('special_allowance_monthly_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='ACTIVE'),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_compensations_employee_id', 'compensations', ['employee_id'])
    op.create_index('ix_compensations_company_id', 'compensations', ['company_id'])

    # 6. compensation_revisions
    op.create_table(
        'compensation_revisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('current_ctc_annual_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('new_ctc_annual_paise', sa.BigInteger(), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(255), nullable=False),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('rejected_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_comp_revisions_employee_id', 'compensation_revisions', ['employee_id'])
    op.create_index('ix_comp_revisions_company_id', 'compensation_revisions', ['company_id'])

    # 7. variable_inputs
    op.create_table(
        'variable_inputs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payroll_periods.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('units', sa.Numeric(8, 2), nullable=True),
        sa.Column('rate_per_unit_paise', sa.BigInteger(), nullable=True),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('rejected_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_variable_inputs_employee_id', 'variable_inputs', ['employee_id'])
    op.create_index('ix_variable_inputs_period_id', 'variable_inputs', ['period_id'])
    op.create_index('ix_variable_inputs_company_id', 'variable_inputs', ['company_id'])

    # 8. payment_batches
    op.create_table(
        'payment_batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payroll_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_number', sa.String(50), nullable=False, unique=True),
        sa.Column('source_account_id', sa.String(100), nullable=False),
        sa.Column('payment_mode', sa.String(30), nullable=False, server_default='NEFT'),
        sa.Column('status', sa.String(30), nullable=False, server_default='DRAFT'),
        sa.Column('total_amount_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_records', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bank_reference_number', sa.String(100), nullable=True),
        sa.Column('submission_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('rejected_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_payment_batches_company_id', 'payment_batches', ['company_id'])
    op.create_index('ix_payment_batches_run_id', 'payment_batches', ['run_id'])

    # 9. payment_batch_items
    op.create_table(
        'payment_batch_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payment_batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('hold_reason', sa.String(500), nullable=True),
        sa.Column('account_number', sa.String(50), nullable=True),
        sa.Column('ifsc_code', sa.String(20), nullable=True),
        sa.Column('account_holder_name', sa.String(100), nullable=True),
        sa.Column('transaction_ref', sa.String(100), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_payment_batch_items_batch_id', 'payment_batch_items', ['batch_id'])
    op.create_index('ix_payment_batch_items_employee_id', 'payment_batch_items', ['employee_id'])

    # 10. payment_batch_bank_files
    op.create_table(
        'payment_batch_bank_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payment_batches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('file_format', sa.String(30), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('file_content', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='GENERATED'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_batch_bank_files_batch_id', 'payment_batch_bank_files', ['batch_id'])

    # 11. full_and_final_settlements
    op.create_table(
        'full_and_final_settlements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('resignation_date', sa.Date(), nullable=False),
        sa.Column('last_working_date', sa.Date(), nullable=False),
        sa.Column('exit_type', sa.String(30), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('notice_period_days_required', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notice_period_days_served', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('shortfall_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(30), nullable=False, server_default='DRAFT'),
        sa.Column('net_payable_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('settlement_breakup', sa.JSON(), nullable=True),
        sa.Column('remarks', sa.String(500), nullable=True),
        sa.Column('notes', sa.String(500), nullable=True),
        sa.Column('statement_path', sa.String(500), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finalized_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_fnf_settlements_employee_id', 'full_and_final_settlements', ['employee_id'])
    op.create_index('ix_fnf_settlements_company_id', 'full_and_final_settlements', ['company_id'])

    # 12. provision_slips
    op.create_table(
        'provision_slips',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payroll_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('employee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('slip_number', sa.String(50), nullable=False, unique=True),
        sa.Column('period_month', sa.Integer(), nullable=False),
        sa.Column('period_year', sa.Integer(), nullable=False),
        sa.Column('gross_earnings_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('total_deductions_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('net_pay_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('breakup', sa.JSON(), nullable=True),
        sa.Column('pdf_path', sa.String(500), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='GENERATED'),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_provision_slips_employee_id', 'provision_slips', ['employee_id'])
    op.create_index('ix_provision_slips_company_id', 'provision_slips', ['company_id'])

    # 13. company_bank_accounts
    op.create_table(
        'company_bank_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bank_name', sa.String(100), nullable=False),
        sa.Column('account_number', sa.String(50), nullable=False),
        sa.Column('ifsc_code', sa.String(20), nullable=False),
        sa.Column('account_holder_name', sa.String(100), nullable=False),
        sa.Column('account_type', sa.String(30), nullable=False, server_default='CURRENT'),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_company_bank_accounts_company_id', 'company_bank_accounts', ['company_id'])

    # 14. payroll_report_exports
    op.create_table(
        'payroll_report_exports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True),
        sa.Column('report_key', sa.String(100), nullable=False),
        sa.Column('file_format', sa.String(10), nullable=False, server_default='csv'),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('file_content', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('filters', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_payroll_report_exports_company_id', 'payroll_report_exports', ['company_id'])


def downgrade():
    op.drop_table('payroll_report_exports')
    op.drop_table('company_bank_accounts')
    op.drop_table('provision_slips')
    op.drop_table('full_and_final_settlements')
    op.drop_table('payment_batch_bank_files')
    op.drop_table('payment_batch_items')
    op.drop_table('payment_batches')
    op.drop_table('variable_inputs')
    op.drop_table('compensation_revisions')
    op.drop_table('compensations')
    op.drop_table('pay_components')
    op.drop_table('payroll_run_employees')
    op.drop_table('payroll_periods')
