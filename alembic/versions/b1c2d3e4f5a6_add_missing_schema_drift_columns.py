"""add missing schema drift columns

Revision ID: b1c2d3e4f5a6
Revises: fb1c2d3e4f5a
Create Date: 2026-08-14 13:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'fb1c2d3e4f5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # 1. departments.employee_capacity
    dept_cols = [c['name'] for c in inspector.get_columns('departments')]
    if 'employee_capacity' not in dept_cols:
        op.add_column('departments', sa.Column('employee_capacity', sa.Integer(), nullable=True, server_default=sa.text('100')))

    # 2. candidate_crm_notes
    if 'candidate_crm_notes' in inspector.get_table_names():
        crm_cols = [c['name'] for c in inspector.get_columns('candidate_crm_notes')]
        if 'channel' not in crm_cols:
            op.add_column('candidate_crm_notes', sa.Column('channel', sa.String(20), nullable=False, server_default=sa.text("'note'")))
        if 'subject' not in crm_cols:
            op.add_column('candidate_crm_notes', sa.Column('subject', sa.String(300), nullable=True))

    # 3. employee_investment_declarations
    if 'employee_investment_declarations' in inspector.get_table_names():
        decl_cols = [c['name'] for c in inspector.get_columns('employee_investment_declarations')]
        if 'tax_regime' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('tax_regime', sa.String(10), nullable=False, server_default=sa.text("'OLD'")))
        if 'section_80g' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('section_80g', sa.Numeric(14, 2), nullable=False, server_default=sa.text('0')))
        if 'hra_claimed' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('hra_claimed', sa.Numeric(14, 2), nullable=False, server_default=sa.text('0')))
        if 'lta_claimed' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('lta_claimed', sa.Numeric(14, 2), nullable=False, server_default=sa.text('0')))
        if 'status' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('status', sa.String(20), nullable=False, server_default=sa.text("'PENDING'")))
        if 'rejection_reason' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('rejection_reason', sa.String(500), nullable=True))
        if 'verified_amount' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('verified_amount', sa.Numeric(14, 2), nullable=True))
        if 'verified_by' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('verified_by', postgresql.UUID(as_uuid=True), nullable=True))
        if 'verified_at' not in decl_cols:
            op.add_column('employee_investment_declarations', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))

    # 4. statutory_compliance_configs
    if 'statutory_compliance_configs' in inspector.get_table_names():
        stat_cols = [c['name'] for c in inspector.get_columns('statutory_compliance_configs')]
        cols_to_add = [
            ('company_name', sa.String(100), sa.text("'Aurix AI Enterprise'"), False),
            ('currency', sa.String(10), sa.text("'INR'"), False),
            ('country', sa.String(50), sa.text("'India'"), False),
            ('timezone', sa.String(50), sa.text("'Asia/Kolkata'"), False),
            ('financial_year_start', sa.String(10), sa.text("'04-01'"), False),
            ('payroll_start_day', sa.Integer(), sa.text('1'), False),
            ('payroll_end_day', sa.Integer(), sa.text('30'), False),
            ('salary_payment_date', sa.Integer(), sa.text('1'), False),
            ('auto_lock_payroll', sa.Boolean(), sa.text('true'), False),
            ('enable_draft_payroll', sa.Boolean(), sa.text('true'), False),
            ('enable_retro_payroll', sa.Boolean(), sa.text('true'), False),
            ('pay_cycle_type', sa.String(20), sa.text("'MONTHLY'"), False),
            ('grace_period_days', sa.Integer(), sa.text('3'), False),
            ('cutoff_date', sa.Integer(), sa.text('25'), False),
            ('preview_days', sa.Integer(), sa.text('5'), False),
            ('bank_name', sa.String(100), None, True),
            ('bank_ifsc', sa.String(20), None, True),
            ('salary_transfer_format', sa.String(50), sa.text("'NEFT_RTGS'"), True),
            ('auto_email_payslips', sa.Boolean(), sa.text('true'), False),
            ('auto_backup_payroll', sa.Boolean(), sa.text('true'), False),
            ('overtime_enabled', sa.Boolean(), sa.text('true'), False),
            ('overtime_multiplier_weekend', sa.Numeric(3, 2), sa.text('1.50'), False),
            ('overtime_multiplier_holiday', sa.Numeric(3, 2), sa.text('2.00'), False),
            ('overtime_multiplier_night', sa.Numeric(3, 2), sa.text('1.25'), False),
            ('settings_data', postgresql.JSONB(astext_type=sa.Text()), None, True),
        ]
        for col_name, col_type, default_val, is_nullable in cols_to_add:
            if col_name not in stat_cols:
                op.add_column(
                    'statutory_compliance_configs',
                    sa.Column(col_name, col_type, nullable=is_nullable, server_default=default_val)
                )


def downgrade() -> None:
    pass
