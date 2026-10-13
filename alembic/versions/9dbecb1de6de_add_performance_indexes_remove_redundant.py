"""add_performance_indexes_remove_redundant

Revision ID: 9dbecb1de6de
Revises: 950ee9372060
Create Date: 2026-10-12 17:14:23.873006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Import idempotent helpers
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from helpers import (
    safe_drop_index, safe_drop_table, safe_drop_column, safe_drop_constraint,
    safe_add_column, safe_create_index, safe_create_unique_constraint,
    safe_alter_column_type, safe_create_table
)

# revision identifiers, used by Alembic.
revision: str = '9dbecb1de6de'
down_revision: Union[str, None] = '950ee9372060'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop indexes idempotently
    safe_drop_index(op.f('ix_payroll_overtime_settings_company_id'), 'payroll_overtime_settings')
    safe_drop_table('payroll_overtime_settings')
    safe_drop_table('payroll_compliance_due_dates')
    safe_drop_index(op.f('ix_payroll_tax_settings_company_id'), 'payroll_tax_settings')
    safe_drop_index(op.f('ix_payroll_tax_settings_tax_code'), 'payroll_tax_settings')
    safe_drop_table('payroll_tax_settings')
    safe_drop_index(op.f('ix_allowances_code'), 'allowances')
    safe_drop_index(op.f('ix_allowances_company_id'), 'allowances')
    safe_drop_table('allowances')
    safe_drop_index(op.f('ix_salary_components_code'), 'salary_components')
    safe_drop_index(op.f('ix_salary_components_company_id'), 'salary_components')
    safe_drop_table('salary_components')
    safe_drop_table('overtime_rules')
    safe_drop_table('payroll_template_versions')
    safe_drop_table('payroll_template_audit_logs')
    safe_drop_table('payroll_tax_audit_logs')
    safe_drop_table('payroll_template_history')
    safe_drop_index(op.f('ix_office_locations_branch'), 'office_locations')
    safe_drop_index(op.f('ix_office_locations_company_id'), 'office_locations')
    safe_drop_table('office_locations')
    safe_drop_table('payroll_overtime_audit_logs')
    safe_drop_table('payroll_compliance_challans')
    safe_drop_table('payroll_tax_history')
    safe_drop_table('payments')
    safe_drop_table('payroll_tax_slabs')
    safe_drop_index(op.f('ix_payroll_compliance_code'), 'payroll_compliance')
    safe_drop_index(op.f('ix_payroll_compliance_company_id'), 'payroll_compliance')
    safe_drop_table('payroll_compliance')
    safe_drop_table('payroll_compliance_history')
    safe_drop_table('salary_component_audit_logs')
    safe_drop_table('allowance_audit_logs')
    safe_drop_table('allowance_history')
    safe_drop_table('payroll_compliance_audit_logs')
    safe_drop_table('payroll_overtime_history')
    safe_drop_index(op.f('ix_payroll_templates_code'), 'payroll_templates')
    safe_drop_index(op.f('ix_payroll_templates_company_id'), 'payroll_templates')
    safe_drop_table('payroll_templates')
    safe_drop_table('salary_component_history')

    # Alter columns - these should be safe as they modify existing columns
    op.alter_column('agent_feedback', 'tags',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('agent_runs', 'trigger',
               existing_type=sa.VARCHAR(length=50),
               server_default=sa.text("'manual'"),
               existing_nullable=False)
    op.alter_column('agent_runs', 'parameters',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('agent_runs', 'context',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('agent_runs', 'status',
               existing_type=sa.VARCHAR(length=50),
               server_default=sa.text("'RUNNING'"),
               existing_nullable=False)
    op.alter_column('agent_runs', 'result',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('attendance_breaks', 'status',
               existing_type=sa.VARCHAR(length=20),
               server_default=None,
               existing_nullable=False)
    safe_drop_index(op.f('ix_attendances_auto_close'), 'attendances', postgresql_where='(check_out_time IS NULL)')
    safe_drop_index(op.f('uq_attendance_open_session'), 'attendances', postgresql_where='(check_out_time IS NULL)')
    op.alter_column('bank_advice_files', 'batch_code',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=50),
               existing_nullable=True)
    op.alter_column('bank_disbursement_records', 'bank_name',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=100),
               existing_nullable=True)
    safe_drop_column('companies', 'feature_entitlements')
    op.alter_column('compliance_obligations', 'challan_number',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=100),
               existing_nullable=True)
    op.alter_column('compliance_obligations', 'acknowledgement_number',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=100),
               existing_nullable=True)
    op.alter_column('compliance_obligations', 'penalty_amount',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               server_default=None,
               nullable=False)
    op.alter_column('compliance_obligations', 'violation_flags',
               existing_type=sa.TEXT(),
               type_=sa.JSON(),
               existing_nullable=True)
    safe_drop_column('employee_bank_accounts', 'upi_id')
    safe_drop_column('employee_bank_accounts', 'passbook_url')
    safe_drop_column('employee_bank_accounts', 'cancelled_cheque_url')
    safe_drop_column('employee_bank_accounts', 'branch')
    safe_drop_index(op.f('ix_employee_docs_emp_cat_hash'), 'employee_documents')
    safe_drop_column('employee_experience', 'ctc')
    safe_drop_column('employee_experience', 'manager_name')
    safe_drop_column('employee_experience', 'experience_certificate_url')
    safe_drop_column('employee_experience', 'salary_slip_url')
    safe_drop_column('employee_experience', 'relieving_letter_url')
    safe_drop_column('employee_experience', 'reason_for_leaving')
    op.alter_column('employee_investment_declarations', 'section_80g',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               nullable=False,
               existing_server_default=sa.text('0'))
    op.alter_column('employee_investment_declarations', 'hra_claimed',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               nullable=False,
               existing_server_default=sa.text('0'))
    op.alter_column('employee_investment_declarations', 'lta_claimed',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               nullable=False,
               existing_server_default=sa.text('0'))
    op.alter_column('employee_investment_declarations', 'status',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'PENDING'"),
               type_=sa.String(length=20),
               nullable=False)
    op.alter_column('employee_investment_declarations', 'rejection_reason',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=500),
               existing_nullable=True)
    op.alter_column('employee_investment_declarations', 'verified_amount',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               server_default=None,
               existing_nullable=True)
    safe_drop_constraint(op.f('employee_invitations_token_key'), 'employee_invitations', type_='unique')
    safe_drop_index(op.f('uq_active_employee_invitation'), 'employee_invitations', postgresql_where="((status)::text = 'PENDING'::text)")
    safe_create_unique_constraint(op.f('uq_employee_invitations_token'), 'employee_invitations', ['token'])
    op.alter_column('employee_policy_acceptances', 'policy_version',
               existing_type=sa.VARCHAR(length=20),
               server_default=None,
               existing_nullable=False)
    op.alter_column('employee_policy_acceptances', 'accepted_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               server_default=sa.text('now()'),
               existing_nullable=False)
    safe_drop_index(op.f('uq_emp_shift_assign_current'), 'employee_shift_assignments', postgresql_where='(effective_to IS NULL)')
    op.alter_column('employee_tax_info', 'tax_regime',
               existing_type=sa.VARCHAR(length=20),
               server_default=None,
               existing_nullable=False)
    op.alter_column('generated_documents', 'variables',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('generated_documents', 'format',
               existing_type=sa.VARCHAR(length=20),
               server_default=sa.text("'pdf'"),
               existing_nullable=False)
    op.alter_column('leave_policies', 'leave_type',
               existing_type=sa.VARCHAR(length=50),
               server_default=None,
               existing_nullable=True)
    op.alter_column('pay_components', 'calculation_method',
               existing_type=sa.VARCHAR(length=30),
               server_default=sa.text("'flat'"),
               existing_nullable=False)
    op.alter_column('pay_cycles', 'name',
               existing_type=sa.VARCHAR(length=100),
               server_default=None,
               existing_nullable=False)
    op.alter_column('pay_cycles', 'frequency',
               existing_type=sa.VARCHAR(length=30),
               server_default=None,
               existing_nullable=False)
    op.alter_column('pay_cycles', 'status',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=30),
               existing_nullable=False,
               existing_server_default=sa.text("'DRAFT'::character varying"))
    safe_drop_index(op.f('ix_pay_cycles_company_period'), 'pay_cycles')
    safe_drop_constraint(op.f('uq_pay_cycle_company_period'), 'pay_cycles', type_='unique')
    op.alter_column('payment_batches', 'payment_mode',
               existing_type=sa.VARCHAR(length=30),
               server_default=sa.text("'NEFT'"),
               existing_nullable=False)
    op.alter_column('payment_transactions', 'billing_cycle',
               existing_type=sa.VARCHAR(length=50),
               server_default=sa.text("'monthly'"),
               existing_nullable=False)
    op.alter_column('payment_transactions', 'currency',
               existing_type=sa.VARCHAR(length=10),
               server_default=sa.text("'INR'"),
               existing_nullable=False)
    op.alter_column('payment_transactions', 'status',
               existing_type=sa.VARCHAR(length=50),
               server_default=sa.text("'CREATED'"),
               existing_nullable=False)
    op.alter_column('payroll_report_exports', 'file_format',
               existing_type=sa.VARCHAR(length=10),
               server_default=sa.text("'csv'"),
               existing_nullable=False)
    op.alter_column('security_policies', 'session_timeout_minutes',
               existing_type=sa.INTEGER(),
               server_default=sa.text('30'),
               existing_nullable=False)
    op.alter_column('security_policies', 'idle_timeout_minutes',
               existing_type=sa.INTEGER(),
               server_default=sa.text('15'),
               existing_nullable=False)
    op.alter_column('security_policies', 'max_concurrent_sessions',
               existing_type=sa.INTEGER(),
               server_default=sa.text('3'),
               existing_nullable=False)
    op.alter_column('security_policies', 'min_password_length',
               existing_type=sa.INTEGER(),
               server_default=sa.text('12'),
               existing_nullable=False)
    op.alter_column('security_policies', 'require_uppercase',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_policies', 'require_lowercase',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_policies', 'require_numbers',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_policies', 'require_special_chars',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_policies', 'mfa_enabled',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_policies', 'aes_256_encryption_enabled',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_policies', 'mask_salary_non_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('security_roles', 'is_system_role',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               existing_nullable=False)
    op.alter_column('security_roles', 'is_active',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('shift_change_requests', 'status',
               existing_type=sa.VARCHAR(length=20),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shift_plan_entries', 'shift_type',
               existing_type=sa.VARCHAR(length=30),
               type_=sa.Enum('DAY', 'NIGHT', 'MORNING', 'EVENING', 'OVERTIME', 'ROTATION', 'HOLIDAY', 'OFF', 'WEEKLY_OFF', 'LEAVE', 'TRAINING', 'WFH', name='shifttype'),
               existing_nullable=False)
    op.alter_column('shift_plan_entries', 'approval_status',
               existing_type=postgresql.ENUM('APPROVED', 'PENDING', 'REJECTED', name='entry_approval_status'),
               type_=sa.Enum('APPROVED', 'PENDING', 'REJECTED', name='entryapprovalstatus'),
               existing_nullable=False,
               existing_server_default=sa.text("'APPROVED'::entry_approval_status"))
    op.alter_column('shift_plans', 'status',
               existing_type=postgresql.ENUM('DRAFT', 'PUBLISHED', 'ARCHIVED', name='shift_plan_status'),
               type_=sa.Enum('DRAFT', 'PUBLISHED', 'ARCHIVED', name='shiftplanstatus'),
               existing_nullable=False,
               existing_server_default=sa.text("'DRAFT'::shift_plan_status"))
    op.alter_column('shift_plans', 'source',
               existing_type=postgresql.ENUM('AI', 'MANUAL', name='shift_plan_source'),
               type_=sa.Enum('AI', 'MANUAL', name='shiftplansource'),
               existing_nullable=False,
               existing_server_default=sa.text("'MANUAL'::shift_plan_source"))
    safe_create_index('ix_shift_plans_status', 'shift_plans', ['status'], unique=False)
    op.alter_column('shifts', 'is_overnight',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'duration_minutes',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'grace_period_minutes',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'break_duration_minutes',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'work_hours',
               existing_type=sa.NUMERIC(precision=4, scale=2),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'is_night_shift',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'night_premium_percent',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'is_active',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'is_default',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('shifts', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    safe_drop_index(op.f('uq_shifts_company_code_active'), 'shifts', postgresql_where='(deleted_at IS NULL)')
    safe_drop_index(op.f('uq_shifts_company_default_active'), 'shifts', postgresql_where='((is_default = true) AND (deleted_at IS NULL))')
    safe_drop_index(op.f('uq_shifts_company_name_active'), 'shifts', postgresql_where='(deleted_at IS NULL)')
    op.alter_column('statutory_compliance_configs', 'company_name',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'Aurix AI Enterprise'"),
               type_=sa.String(length=100),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'currency',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'INR'"),
               type_=sa.String(length=10),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'country',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'India'"),
               type_=sa.String(length=50),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'timezone',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'Asia/Kolkata'"),
               type_=sa.String(length=50),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'financial_year_start',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'04-01'"),
               type_=sa.String(length=10),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'payroll_start_day',
               existing_type=sa.INTEGER(),
               server_default=sa.text('1'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'payroll_end_day',
               existing_type=sa.INTEGER(),
               server_default=sa.text('30'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'salary_payment_date',
               existing_type=sa.INTEGER(),
               server_default=sa.text('1'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'auto_lock_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'enable_draft_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'enable_retro_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'pay_cycle_type',
               existing_type=sa.VARCHAR(length=550),
               server_default=sa.text("'MONTHLY'"),
               type_=sa.String(length=20),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'grace_period_days',
               existing_type=sa.INTEGER(),
               server_default=sa.text('3'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'cutoff_date',
               existing_type=sa.INTEGER(),
               server_default=sa.text('25'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'preview_days',
               existing_type=sa.INTEGER(),
               server_default=sa.text('5'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'overtime_enabled',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'overtime_multiplier_holiday',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               nullable=False,
               existing_server_default=sa.text('2.00'))
    op.alter_column('statutory_compliance_configs', 'overtime_multiplier_weekend',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               nullable=False,
               existing_server_default=sa.text('1.50'))
    op.alter_column('statutory_compliance_configs', 'overtime_multiplier_night',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               nullable=False,
               existing_server_default=sa.text('1.25'))
    op.alter_column('statutory_compliance_configs', 'bank_name',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=100),
               existing_nullable=False,
               existing_server_default=sa.text("'HDFC Bank'::character varying"))
    op.alter_column('statutory_compliance_configs', 'bank_ifsc',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=20),
               existing_nullable=False,
               existing_server_default=sa.text("'HDFC0001234'::character varying"))
    op.alter_column('statutory_compliance_configs', 'salary_transfer_format',
               existing_type=sa.VARCHAR(length=550),
               type_=sa.String(length=50),
               existing_nullable=False,
               existing_server_default=sa.text("'NEFT'::character varying"))
    op.alter_column('statutory_compliance_configs', 'auto_email_payslips',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'auto_backup_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'settings_data',
               existing_type=sa.TEXT(),
               type_=postgresql.JSONB(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('subscriptions', 'plan',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=100),
               nullable=True)
    op.alter_column('subscriptions', 'access_status',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('subscriptions', 'access_type',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('subscriptions', 'payment_status',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('subscriptions', 'access_source',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('subscriptions', 'access_granted_by',
               existing_type=sa.VARCHAR(length=255),
               type_=sa.String(length=100),
               existing_nullable=True)
    op.alter_column('subscriptions', 'mrr',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=True)
    safe_drop_constraint(op.f('uq_subscriptions_company_id'), 'subscriptions', type_='unique')
    op.alter_column('user_sessions', 'is_active',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('user_sessions', 'is_active',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    safe_create_unique_constraint(op.f('uq_subscriptions_company_id'), 'subscriptions', ['company_id'], postgresql_nulls_not_distinct=False)
    op.alter_column('subscriptions', 'mrr',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=False)
    op.alter_column('subscriptions', 'access_granted_by',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=255),
               existing_nullable=True)
    op.alter_column('subscriptions', 'access_source',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    op.alter_column('subscriptions', 'payment_status',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    op.alter_column('subscriptions', 'access_type',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    op.alter_column('subscriptions', 'access_status',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    op.alter_column('subscriptions', 'plan',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=50),
               nullable=False)
    op.alter_column('statutory_compliance_configs', 'settings_data',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('statutory_compliance_configs', 'auto_backup_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'auto_email_payslips',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'salary_transfer_format',
               existing_type=sa.String(length=50),
               type_=sa.VARCHAR(length=550),
               existing_nullable=False,
               existing_server_default=sa.text("'NEFT'::character varying"))
    op.alter_column('statutory_compliance_configs', 'bank_ifsc',
               existing_type=sa.String(length=20),
               type_=sa.VARCHAR(length=550),
               existing_nullable=False,
               existing_server_default=sa.text("'HDFC0001234'::character varying"))
    op.alter_column('statutory_compliance_configs', 'bank_name',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=550),
               existing_nullable=False,
               existing_server_default=sa.text("'HDFC Bank'::character varying"))
    op.alter_column('statutory_compliance_configs', 'overtime_multiplier_night',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               nullable=True,
               existing_server_default=sa.text('1.25'))
    op.alter_column('statutory_compliance_configs', 'overtime_multiplier_weekend',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               nullable=True,
               existing_server_default=sa.text('1.50'))
    op.alter_column('statutory_compliance_configs', 'overtime_multiplier_holiday',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               nullable=True,
               existing_server_default=sa.text('2.00'))
    op.alter_column('statutory_compliance_configs', 'overtime_enabled',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'preview_days',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'cutoff_date',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'grace_period_days',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'pay_cycle_type',
               existing_type=sa.String(length=20),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'enable_retro_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'enable_draft_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'auto_lock_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'salary_payment_date',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'payroll_end_day',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'payroll_start_day',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'financial_year_start',
               existing_type=sa.String(length=10),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'timezone',
               existing_type=sa.String(length=50),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'country',
               existing_type=sa.String(length=50),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'currency',
               existing_type=sa.String(length=10),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    op.alter_column('statutory_compliance_configs', 'company_name',
               existing_type=sa.String(length=100),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    safe_create_index(op.f('uq_shifts_company_name_active'), 'shifts', ['company_id', 'name'], unique=True, postgresql_where='(deleted_at IS NULL)')
    safe_create_index(op.f('uq_shifts_company_default_active'), 'shifts', ['company_id'], unique=True, postgresql_where='((is_default = true) AND (deleted_at IS NULL))')
    safe_create_index(op.f('uq_shifts_company_code_active'), 'shifts', ['company_id', 'code'], unique=True, postgresql_where='(deleted_at IS NULL)')
    op.alter_column('shifts', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('shifts', 'is_default',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               existing_nullable=False)
    op.alter_column('shifts', 'is_active',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_nullable=False)
    op.alter_column('shifts', 'night_premium_percent',
               existing_type=sa.NUMERIC(precision=5, scale=2),
               server_default=sa.text('0'),
               existing_nullable=False)
    op.alter_column('shifts', 'is_night_shift',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               existing_nullable=False)
    op.alter_column('shifts', 'work_hours',
               existing_type=sa.NUMERIC(precision=4, scale=2),
               server_default=sa.text('0.0'),
               existing_nullable=False)
    op.alter_column('shifts', 'break_duration_minutes',
               existing_type=sa.INTEGER(),
               server_default=sa.text('60'),
               existing_nullable=False)
    op.alter_column('shifts', 'grace_period_minutes',
               existing_type=sa.INTEGER(),
               server_default=sa.text('15'),
               existing_nullable=False)
    op.alter_column('shifts', 'duration_minutes',
               existing_type=sa.INTEGER(),
               server_default=sa.text('0'),
               existing_nullable=False)
    op.alter_column('shifts', 'is_overnight',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               existing_nullable=False)
    safe_drop_index('ix_shift_plans_status', 'shift_plans')
    op.alter_column('shift_plans', 'source',
               existing_type=sa.Enum('AI', 'MANUAL', name='shiftplansource'),
               type_=postgresql.ENUM('AI', 'MANUAL', name='shift_plan_source'),
               existing_nullable=False,
               existing_server_default=sa.text("'MANUAL'::shift_plan_source"))
    op.alter_column('shift_plans', 'status',
               existing_type=sa.Enum('DRAFT', 'PUBLISHED', 'ARCHIVED', name='shiftplanstatus'),
               type_=postgresql.ENUM('DRAFT', 'PUBLISHED', 'ARCHIVED', name='shift_plan_status'),
               existing_nullable=False,
               existing_server_default=sa.text("'DRAFT'::shift_plan_status"))
    op.alter_column('shift_plan_entries', 'approval_status',
               existing_type=sa.Enum('APPROVED', 'PENDING', 'REJECTED', name='entryapprovalstatus'),
               type_=postgresql.ENUM('APPROVED', 'PENDING', 'REJECTED', name='entry_approval_status'),
               existing_nullable=False,
               existing_server_default=sa.text("'APPROVED'::entry_approval_status"))
    op.alter_column('shift_plan_entries', 'shift_type',
               existing_type=sa.Enum('DAY', 'NIGHT', 'MORNING', 'EVENING', 'OVERTIME', 'ROTATION', 'HOLIDAY', 'OFF', 'WEEKLY_OFF', 'LEAVE', 'TRAINING', 'WFH', name='shifttype'),
               type_=sa.VARCHAR(length=30),
               existing_nullable=False)
    op.alter_column('shift_change_requests', 'status',
               existing_type=sa.VARCHAR(length=20),
               server_default=sa.text("'PENDING'::character varying"),
               existing_nullable=False)
    op.alter_column('security_roles', 'is_active',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_roles', 'is_system_role',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'mask_salary_non_payroll',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'aes_256_encryption_enabled',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'mfa_enabled',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'require_special_chars',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'require_numbers',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'require_lowercase',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'require_uppercase',
               existing_type=sa.BOOLEAN(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'min_password_length',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'max_concurrent_sessions',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'idle_timeout_minutes',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('security_policies', 'session_timeout_minutes',
               existing_type=sa.INTEGER(),
               server_default=None,
               existing_nullable=False)
    op.alter_column('payroll_report_exports', 'file_format',
               existing_type=sa.VARCHAR(length=10),
               server_default=None,
               existing_nullable=False)
    op.alter_column('payment_transactions', 'status',
               existing_type=sa.VARCHAR(length=50),
               server_default=None,
               existing_nullable=False)
    op.alter_column('payment_transactions', 'currency',
               existing_type=sa.VARCHAR(length=10),
               server_default=None,
               existing_nullable=False)
    op.alter_column('payment_transactions', 'billing_cycle',
               existing_type=sa.VARCHAR(length=50),
               server_default=None,
               existing_nullable=False)
    op.alter_column('payment_batches', 'payment_mode',
               existing_type=sa.VARCHAR(length=30),
               server_default=None,
               existing_nullable=False)
    safe_create_unique_constraint(op.f('uq_pay_cycle_company_period'), 'pay_cycles', ['company_id', 'period_month', 'period_year'], postgresql_nulls_not_distinct=False)
    safe_create_index(op.f('ix_pay_cycles_company_period'), 'pay_cycles', ['company_id', 'period_year', 'period_month'], unique=False)
    op.alter_column('pay_cycles', 'status',
               existing_type=sa.String(length=30),
               type_=sa.VARCHAR(length=20),
               existing_nullable=False,
               existing_server_default=sa.text("'DRAFT'::character varying"))
    op.alter_column('pay_cycles', 'frequency',
               existing_type=sa.VARCHAR(length=30),
               server_default=sa.text("'MONTHLY'::character varying"),
               existing_nullable=False)
    op.alter_column('pay_cycles', 'name',
               existing_type=sa.VARCHAR(length=100),
               server_default=sa.text("'Monthly Payroll Cycle'::character varying"),
               existing_nullable=False)
    op.alter_column('pay_components', 'calculation_method',
               existing_type=sa.VARCHAR(length=30),
               server_default=None,
               existing_nullable=False)
    op.alter_column('leave_policies', 'leave_type',
               existing_type=sa.VARCHAR(length=50),
               server_default=sa.text("'ANNUAL'::character varying"),
               existing_nullable=True)
    op.alter_column('generated_documents', 'format',
               existing_type=sa.VARCHAR(length=20),
               server_default=None,
               existing_nullable=False)
    op.alter_column('generated_documents', 'variables',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('employee_tax_info', 'tax_regime',
               existing_type=sa.VARCHAR(length=20),
               server_default=sa.text("'NEW'::character varying"),
               existing_nullable=False)
    safe_create_index(op.f('uq_emp_shift_assign_current'), 'employee_shift_assignments', ['employee_id'], unique=True, postgresql_where='(effective_to IS NULL)')
    op.alter_column('employee_policy_acceptances', 'accepted_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               server_default=None,
               existing_nullable=False)
    op.alter_column('employee_policy_acceptances', 'policy_version',
               existing_type=sa.VARCHAR(length=20),
               server_default=sa.text("'1.0'::character varying"),
               existing_nullable=False)
    safe_drop_constraint(op.f('uq_employee_invitations_token'), 'employee_invitations', type_='unique')
    safe_create_index(op.f('uq_active_employee_invitation'), 'employee_invitations', ['company_id', sa.literal_column('lower(email::text)')], unique=True, postgresql_where="((status)::text = 'PENDING'::text)")
    safe_create_unique_constraint(op.f('employee_invitations_token_key'), 'employee_invitations', ['token'], postgresql_nulls_not_distinct=False)
    op.alter_column('employee_investment_declarations', 'verified_amount',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               server_default=sa.text('0'),
               existing_nullable=True)
    op.alter_column('employee_investment_declarations', 'rejection_reason',
               existing_type=sa.String(length=500),
               type_=sa.VARCHAR(length=550),
               existing_nullable=True)
    op.alter_column('employee_investment_declarations', 'status',
               existing_type=sa.String(length=20),
               server_default=None,
               type_=sa.VARCHAR(length=550),
               nullable=True)
    op.alter_column('employee_investment_declarations', 'lta_claimed',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               nullable=True,
               existing_server_default=sa.text('0'))
    op.alter_column('employee_investment_declarations', 'hra_claimed',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               nullable=True,
               existing_server_default=sa.text('0'))
    op.alter_column('employee_investment_declarations', 'section_80g',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               nullable=True,
               existing_server_default=sa.text('0'))
    safe_add_column('employee_experience', sa.Column('reason_for_leaving', sa.TEXT(), autoincrement=False, nullable=True))
    safe_add_column('employee_experience', sa.Column('relieving_letter_url', sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    safe_add_column('employee_experience', sa.Column('salary_slip_url', sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    safe_add_column('employee_experience', sa.Column('experience_certificate_url', sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    safe_add_column('employee_experience', sa.Column('manager_name', sa.VARCHAR(length=150), autoincrement=False, nullable=True))
    safe_add_column('employee_experience', sa.Column('ctc', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True))
    safe_create_index(op.f('ix_employee_docs_emp_cat_hash'), 'employee_documents', ['employee_id', 'category_id', 'document_hash'], unique=False)
    safe_add_column('employee_bank_accounts', sa.Column('branch', sa.VARCHAR(length=100), autoincrement=False, nullable=True))
    safe_add_column('employee_bank_accounts', sa.Column('cancelled_cheque_url', sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    safe_add_column('employee_bank_accounts', sa.Column('passbook_url', sa.VARCHAR(length=500), autoincrement=False, nullable=True))
    safe_add_column('employee_bank_accounts', sa.Column('upi_id', sa.VARCHAR(length=50), autoincrement=False, nullable=True))
    op.alter_column('compliance_obligations', 'violation_flags',
               existing_type=sa.JSON(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('compliance_obligations', 'penalty_amount',
               existing_type=sa.NUMERIC(precision=14, scale=2),
               server_default=sa.text('0'),
               nullable=True)
    op.alter_column('compliance_obligations', 'acknowledgement_number',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=550),
               existing_nullable=True)
    op.alter_column('compliance_obligations', 'challan_number',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=550),
               existing_nullable=True)
    safe_add_column('companies', sa.Column('feature_entitlements', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True))
    op.alter_column('bank_disbursement_records', 'bank_name',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=550),
               existing_nullable=True)
    op.alter_column('bank_advice_files', 'batch_code',
               existing_type=sa.String(length=50),
               type_=sa.VARCHAR(length=550),
               existing_nullable=True)
    safe_create_index(op.f('uq_attendance_open_session'), 'attendances', ['employee_id'], unique=True, postgresql_where='(check_out_time IS NULL)')
    safe_create_index(op.f('ix_attendances_auto_close'), 'attendances', ['check_out_time'], unique=False, postgresql_where='(check_out_time IS NULL)')
    op.alter_column('attendance_breaks', 'status',
               existing_type=sa.VARCHAR(length=20),
               server_default=sa.text("'ACTIVE'::character varying"),
               existing_nullable=False)
    op.alter_column('agent_runs', 'result',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('agent_runs', 'status',
               existing_type=sa.VARCHAR(length=50),
               server_default=None,
               existing_nullable=False)
    op.alter_column('agent_runs', 'context',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('agent_runs', 'parameters',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('agent_runs', 'trigger',
               existing_type=sa.VARCHAR(length=50),
               server_default=None,
               existing_nullable=False)
    op.alter_column('agent_feedback', 'tags',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True)

    # Recreate tables in downgrade - use safe_create_table
    safe_create_table('salary_component_history', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('component_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('snapshot', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['component_id'], ['salary_components.id'], name=op.f('fk_salary_component_history_component_id_salary_components'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_salary_component_history'))
    ])
    safe_create_table('payroll_templates', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('template_name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('template_code', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('category', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('description', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('doc_format', sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column('language', sa.VARCHAR(length=10), autoincrement=False, nullable=False),
        sa.Column('status', sa.VARCHAR(length=30), server_default=sa.text("'PUBLISHED'::character varying"), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False),
        sa.Column('is_default', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('styling_theme', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('html_content', sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column('header_logo_url', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('footer_text', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_payroll_templates_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_templates')),
        sa.UniqueConstraint('company_id', 'template_code', name=op.f('uq_payroll_template_code'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    ])
    safe_create_index(op.f('ix_payroll_templates_company_id'), 'payroll_templates', ['company_id'], unique=False)
    safe_create_index(op.f('ix_payroll_templates_code'), 'payroll_templates', ['template_code'], unique=False)
    safe_create_table('payroll_overtime_history', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('setting_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('snapshot', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['setting_id'], ['payroll_overtime_settings.id'], name=op.f('fk_payroll_overtime_history_setting_id_payroll_overtime_76ad'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_overtime_history'))
    ])
    safe_create_table('payroll_compliance_audit_logs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('compliance_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('actor', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('previous_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('updated_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('ip_address', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('browser', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['compliance_id'], ['payroll_compliance.id'], name=op.f('fk_payroll_compliance_audit_logs_compliance_id_payroll__4d93'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_compliance_audit_logs'))
    ])
    safe_create_table('allowance_history', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('allowance_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('snapshot', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['allowance_id'], ['allowances.id'], name=op.f('fk_allowance_history_allowance_id_allowances'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_allowance_history'))
    ])
    safe_create_table('allowance_audit_logs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('allowance_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('actor', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('previous_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('updated_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('ip_address', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('browser', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['allowance_id'], ['allowances.id'], name=op.f('fk_allowance_audit_logs_allowance_id_allowances'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_allowance_audit_logs'))
    ])
    safe_create_table('salary_component_audit_logs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('component_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('actor', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('previous_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('updated_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('ip_address', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('browser', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['component_id'], ['salary_components.id'], name=op.f('fk_salary_component_audit_logs_component_id_salary_components'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_salary_component_audit_logs'))
    ])
    safe_create_table('payroll_compliance_history', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('compliance_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('snapshot', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['compliance_id'], ['payroll_compliance.id'], name=op.f('fk_payroll_compliance_history_compliance_id_payroll_compliance'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_compliance_history'))
    ])
    safe_create_table('payroll_compliance', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('compliance_name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('compliance_code', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('category', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('description', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('financial_year', sa.VARCHAR(length=20), server_default=sa.text("'2026-2027'::character varying"), autoincrement=False, nullable=False),
        sa.Column('state', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('status', sa.VARCHAR(length=30), server_default=sa.text("'COMPLIANT'::character varying"), autoincrement=False, nullable=False),
        sa.Column('filing_frequency', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('due_day_of_month', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('is_enabled', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('auto_file', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('auto_remind', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('compliance_score', sa.INTEGER(), server_default=sa.text('100'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_payroll_compliance_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_compliance')),
        sa.UniqueConstraint('company_id', 'compliance_code', name=op.f('uq_payroll_compliance_code'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    ])
    safe_create_index(op.f('ix_payroll_compliance_company_id'), 'payroll_compliance', ['company_id'], unique=False)
    safe_create_index(op.f('ix_payroll_compliance_code'), 'payroll_compliance', ['compliance_code'], unique=False)
    safe_create_table('payroll_tax_slabs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('tax_setting_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('min_income', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=False),
        sa.Column('max_income', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('tax_rate', sa.NUMERIC(precision=7, scale=4), autoincrement=False, nullable=False),
        sa.Column('flat_amount', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['tax_setting_id'], ['payroll_tax_settings.id'], name=op.f('fk_payroll_tax_slabs_tax_setting_id_payroll_tax_settings'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_tax_slabs'))
    ])
    safe_create_table('payments', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('amount', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
        sa.Column('currency', sa.VARCHAR(length=10), autoincrement=False, nullable=False),
        sa.Column('gateway', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('invoice_number', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('status', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('razorpay_order_id', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('razorpay_payment_id', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column('payment_date', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_payments_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    ])
    safe_create_table('payroll_tax_history', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('tax_setting_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('snapshot', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['tax_setting_id'], ['payroll_tax_settings.id'], name=op.f('fk_payroll_tax_history_tax_setting_id_payroll_tax_settings'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_tax_history'))
    ])
    safe_create_table('payroll_compliance_challans', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('compliance_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('challan_type', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('period_month', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('period_year', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('total_amount', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=False),
        sa.Column('employee_count', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('trrn_number', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('status', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('file_payload', sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['compliance_id'], ['payroll_compliance.id'], name=op.f('fk_payroll_compliance_challans_compliance_id_payroll_compliance'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_compliance_challans'))
    ])
    safe_create_table('payroll_overtime_audit_logs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('setting_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('actor', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('previous_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('updated_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('ip_address', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('browser', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['setting_id'], ['payroll_overtime_settings.id'], name=op.f('fk_payroll_overtime_audit_logs_setting_id_payroll_overt_7255'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_overtime_audit_logs'))
    ])
    safe_create_table('office_locations', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('name', sa.VARCHAR(length=150), autoincrement=False, nullable=False),
        sa.Column('branch', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('latitude', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
        sa.Column('longitude', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
        sa.Column('radius_meters', sa.DOUBLE_PRECISION(precision=53), server_default=sa.text('200.0'), autoincrement=False, nullable=False),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('office_locations_company_id_fkey'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('office_locations_pkey'))
    ])
    safe_create_index(op.f('ix_office_locations_company_id'), 'office_locations', ['company_id'], unique=False)
    safe_create_index(op.f('ix_office_locations_branch'), 'office_locations', ['branch'], unique=False)
    safe_create_table('payroll_template_history', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('template_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['payroll_templates.id'], name=op.f('fk_payroll_template_history_template_id_payroll_templates'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_template_history'))
    ])
    safe_create_table('payroll_tax_audit_logs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('tax_setting_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('actor', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('previous_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('updated_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('ip_address', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('browser', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['tax_setting_id'], ['payroll_tax_settings.id'], name=op.f('fk_payroll_tax_audit_logs_tax_setting_id_payroll_tax_settings'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_tax_audit_logs'))
    ])
    safe_create_table('payroll_template_audit_logs', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('template_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('action', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('actor', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('previous_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('updated_value', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('ip_address', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('browser', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['payroll_templates.id'], name=op.f('fk_payroll_template_audit_logs_template_id_payroll_templates'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_template_audit_logs'))
    ])
    safe_create_table('payroll_template_versions', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('template_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('html_content', sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column('changed_by', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('reason', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['payroll_templates.id'], name=op.f('fk_payroll_template_versions_template_id_payroll_templates'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_template_versions'))
    ])
    safe_create_table('overtime_rules', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('setting_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('rule_name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('rule_code', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('department', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('designation', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('multiplier', sa.NUMERIC(precision=5, scale=2), autoincrement=False, nullable=False),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['setting_id'], ['payroll_overtime_settings.id'], name=op.f('fk_overtime_rules_setting_id_payroll_overtime_settings'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_overtime_rules'))
    ])
    safe_create_table('salary_components', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('code', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('component_type', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('category', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('description', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('display_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('payroll_code', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('display_order', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False),
        sa.Column('calc_type', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('formula_expr', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('fixed_amount', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('percentage_value', sa.NUMERIC(precision=7, scale=4), autoincrement=False, nullable=True),
        sa.Column('is_system', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('is_mandatory', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('is_taxable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('pf_applicable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('esi_applicable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('pt_applicable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('included_in_ctc', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('included_in_gross', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('included_in_net', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('appears_on_payslip', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('employee_editable', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('hr_editable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_salary_components_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_salary_components')),
        sa.UniqueConstraint('company_id', 'code', name=op.f('uq_salary_component_company_code'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    ])
    safe_create_index(op.f('ix_salary_components_company_id'), 'salary_components', ['company_id'], unique=False)
    safe_create_index(op.f('ix_salary_components_code'), 'salary_components', ['code'], unique=False)
    safe_create_table('allowances', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('display_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column('code', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('description', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('category', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('earning_type', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('is_variable', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('frequency', sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column('is_recurring', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('calc_type', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('formula_expr', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('default_amount', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=False),
        sa.Column('min_limit', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('max_limit', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('currency', sa.VARCHAR(length=10), server_default=sa.text("'INR'::character varying"), autoincrement=False, nullable=False),
        sa.Column('taxability_type', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('exemption_limit_monthly', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('exemption_limit_annual', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('pf_applicable', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('esi_applicable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('pt_applicable', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('lwf_applicable', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('included_in_ctc', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('included_in_gross', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('included_in_net', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('appears_on_payslip', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('is_mandatory', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('display_order', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_allowances_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_allowances')),
        sa.UniqueConstraint('company_id', 'code', name=op.f('uq_allowance_company_code'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    ])
    safe_create_index(op.f('ix_allowances_company_id'), 'allowances', ['company_id'], unique=False)
    safe_create_index(op.f('ix_allowances_code'), 'allowances', ['code'], unique=False)
    safe_create_table('payroll_tax_settings', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('tax_name', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('tax_code', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('tax_type', sa.VARCHAR(length=40), autoincrement=False, nullable=False),
        sa.Column('description', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
        sa.Column('financial_year', sa.VARCHAR(length=20), server_default=sa.text("'2026-2027'::character varying"), autoincrement=False, nullable=False),
        sa.Column('country', sa.VARCHAR(length=10), server_default=sa.text("'IND'::character varying"), autoincrement=False, nullable=False),
        sa.Column('state', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column('calc_type', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('employee_rate', sa.NUMERIC(precision=7, scale=4), autoincrement=False, nullable=True),
        sa.Column('employer_rate', sa.NUMERIC(precision=7, scale=4), autoincrement=False, nullable=True),
        sa.Column('wage_ceiling', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('std_deduction', sa.NUMERIC(precision=14, scale=2), autoincrement=False, nullable=True),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('display_order', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_payroll_tax_settings_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_tax_settings')),
        sa.UniqueConstraint('company_id', 'tax_code', name=op.f('uq_payroll_tax_company_code'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    ])
    safe_create_index(op.f('ix_payroll_tax_settings_tax_code'), 'payroll_tax_settings', ['tax_code'], unique=False)
    safe_create_index(op.f('ix_payroll_tax_settings_company_id'), 'payroll_tax_settings', ['company_id'], unique=False)
    safe_create_table('payroll_compliance_due_dates', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('compliance_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('title', sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column('due_date', sa.DATE(), autoincrement=False, nullable=False),
        sa.Column('period', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
        sa.Column('status', sa.VARCHAR(length=30), autoincrement=False, nullable=False),
        sa.Column('challan_number', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(['compliance_id'], ['payroll_compliance.id'], name=op.f('fk_payroll_compliance_due_dates_compliance_id_payroll_c_3fbb'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_compliance_due_dates'))
    ])
    safe_create_table('payroll_overtime_settings', [
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('company_id', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('overtime_enabled', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('overtime_code', sa.VARCHAR(length=50), server_default=sa.text("'OT_POLICY_STD'::character varying"), autoincrement=False, nullable=False),
        sa.Column('calc_method', sa.VARCHAR(length=40), server_default=sa.text("'HOURLY_MULTIPLIER'::character varying"), autoincrement=False, nullable=False),
        sa.Column('standard_multiplier', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('1.5'), autoincrement=False, nullable=False),
        sa.Column('weekend_multiplier', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('1.5'), autoincrement=False, nullable=False),
        sa.Column('holiday_multiplier', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('2.0'), autoincrement=False, nullable=False),
        sa.Column('night_shift_multiplier', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('1.25'), autoincrement=False, nullable=False),
        sa.Column('emergency_multiplier', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('2.5'), autoincrement=False, nullable=False),
        sa.Column('min_hours_per_day', sa.NUMERIC(precision=4, scale=2), server_default=sa.text('1.0'), autoincrement=False, nullable=False),
        sa.Column('max_hours_per_day', sa.NUMERIC(precision=4, scale=2), server_default=sa.text('4.0'), autoincrement=False, nullable=False),
        sa.Column('max_hours_per_week', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('16.0'), autoincrement=False, nullable=False),
        sa.Column('max_hours_per_month', sa.NUMERIC(precision=5, scale=2), server_default=sa.text('50.0'), autoincrement=False, nullable=False),
        sa.Column('auto_approval_enabled', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('auto_approval_threshold_hours', sa.NUMERIC(precision=4, scale=2), server_default=sa.text('2.0'), autoincrement=False, nullable=False),
        sa.Column('require_manager_approval', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('comp_off_enabled', sa.BOOLEAN(), server_default=sa.text('true'), autoincrement=False, nullable=False),
        sa.Column('comp_off_expiry_days', sa.INTEGER(), server_default=sa.text('90'), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_payroll_overtime_settings_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payroll_overtime_settings'))
    ])
    safe_create_index(op.f('ix_payroll_overtime_settings_company_id'), 'payroll_overtime_settings', ['company_id'], unique=False)