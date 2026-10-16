"""Add canonical period fields and migrate pay_cycles data to payroll_periods

Revision ID: a1b2c3d4e5f6
Revises: 2329529ee821
Create Date: 2026-10-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '2329529ee821'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to payroll_periods
    op.add_column('payroll_periods', sa.Column('processing_date', sa.Date(), nullable=True))
    op.add_column('payroll_periods', sa.Column('payment_date', sa.Date(), nullable=True))
    op.add_column('payroll_periods', sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('payroll_periods', sa.Column('locked_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('payroll_periods', sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True))
    
    # Add unique constraint for company_id, period_month, period_year
    op.create_unique_constraint('uq_period_company_month_year', 'payroll_periods', ['company_id', 'period_month', 'period_year'])
    
    # Migrate data from pay_cycles to payroll_periods
    # Only migrate cycles that don't already have a corresponding period
    op.execute("""
        INSERT INTO payroll_periods (
            id, company_id, name, start_date, end_date, pay_date, 
            processing_date, payment_date, period_month, period_year, 
            status, is_locked, locked_by, locked_at, remarks, created_at, updated_at
        )
        SELECT 
            pc.id, pc.company_id, pc.name, pc.start_date, pc.end_date, pc.payment_date,
            pc.processing_date, pc.payment_date, pc.period_month, pc.period_year,
            CASE pc.status
                WHEN 'DRAFT' THEN 'OPEN'
                WHEN 'SCHEDULED' THEN 'OPEN'
                WHEN 'RUNNING' THEN 'PROCESSING'
                WHEN 'LOCKED' THEN 'LOCKED'
                WHEN 'PROCESSING' THEN 'PROCESSING'
                WHEN 'COMPLETED' THEN 'CLOSED'
                WHEN 'CANCELLED' THEN 'VOID'
                WHEN 'ARCHIVED' THEN 'CLOSED'
                ELSE 'OPEN'
            END,
            pc.is_locked,
            pc.locked_by,
            pc.locked_at,
            pc.remarks,
            pc.created_at,
            pc.updated_at
        FROM pay_cycles pc
        WHERE NOT EXISTS (
            SELECT 1 FROM payroll_periods pp 
            WHERE pp.company_id = pc.company_id 
            AND pp.period_month = pc.period_month 
            AND pp.period_year = pc.period_year
        )
        AND pc.company_id IS NOT NULL
    """)
    
    # Set payment_date default to pay_date where null
    op.execute("UPDATE payroll_periods SET payment_date = pay_date WHERE payment_date IS NULL")
    # Set processing_date default to end_date where null
    op.execute("UPDATE payroll_periods SET processing_date = end_date WHERE processing_date IS NULL")


def downgrade() -> None:
    # Drop unique constraint
    op.drop_constraint('uq_period_company_month_year', 'payroll_periods', type_='unique')
    
    # Drop new columns
    op.drop_column('payroll_periods', 'locked_at')
    op.drop_column('payroll_periods', 'locked_by')
    op.drop_column('payroll_periods', 'is_locked')
    op.drop_column('payroll_periods', 'payment_date')
    op.drop_column('payroll_periods', 'processing_date')
    
    # Note: We don't delete migrated data in downgrade as it could be user data