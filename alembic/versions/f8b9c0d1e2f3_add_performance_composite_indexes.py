"""add_performance_composite_indexes

Revision ID: f8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-07-21 14:42:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Employees performance indexes
    op.create_index('ix_employees_company_id', 'employees', ['company_id'], unique=False, if_not_exists=True)
    op.create_index('ix_employees_company_status', 'employees', ['company_id', 'status', 'is_deleted'], unique=False, if_not_exists=True)
    op.create_index('ix_employees_company_department', 'employees', ['company_id', 'department', 'is_deleted'], unique=False, if_not_exists=True)

    # Applications performance indexes
    op.create_index('ix_applications_company_id', 'applications', ['company_id'], unique=False, if_not_exists=True)
    op.create_index('ix_applications_candidate_id', 'applications', ['candidate_id'], unique=False, if_not_exists=True)
    op.create_index('ix_applications_company_status', 'applications', ['company_id', 'status'], unique=False, if_not_exists=True)
    op.create_index('ix_applications_job_status', 'applications', ['job_id', 'status'], unique=False, if_not_exists=True)

    # Payroll performance indexes
    op.create_index('ix_pay_cycles_company_period', 'pay_cycles', ['company_id', 'period_year', 'period_month'], unique=False, if_not_exists=True)
    op.create_index('ix_payslips_run_employee', 'payslips', ['payroll_run_id', 'employee_id'], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_index('ix_payslips_run_employee', table_name='payslips', if_exists=True)
    op.drop_index('ix_pay_cycles_company_period', table_name='pay_cycles', if_exists=True)
    op.drop_index('ix_applications_job_status', table_name='applications', if_exists=True)
    op.drop_index('ix_applications_company_status', table_name='applications', if_exists=True)
    op.drop_index('ix_applications_candidate_id', table_name='applications', if_exists=True)
    op.drop_index('ix_applications_company_id', table_name='applications', if_exists=True)
    op.drop_index('ix_employees_company_department', table_name='employees', if_exists=True)
    op.drop_index('ix_employees_company_status', table_name='employees', if_exists=True)
    op.drop_index('ix_employees_company_id', table_name='employees', if_exists=True)
