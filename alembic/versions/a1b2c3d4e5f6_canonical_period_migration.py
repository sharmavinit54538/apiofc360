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
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Add new columns to payroll_periods if not present
    existing_cols = {c['name'] for c in insp.get_columns('payroll_periods')}
    if 'processing_date' not in existing_cols:
        op.add_column('payroll_periods', sa.Column('processing_date', sa.Date(), nullable=True))
    if 'payment_date' not in existing_cols:
        op.add_column('payroll_periods', sa.Column('payment_date', sa.Date(), nullable=True))
    if 'is_locked' not in existing_cols:
        op.add_column('payroll_periods', sa.Column('is_locked', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'locked_by' not in existing_cols:
        op.add_column('payroll_periods', sa.Column('locked_by', postgresql.UUID(as_uuid=True), nullable=True))
    if 'locked_at' not in existing_cols:
        op.add_column('payroll_periods', sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True))

    # Add unique constraint for company_id, period_month, period_year if not present
    existing_constraints = {c['name'] for c in insp.get_unique_constraints('payroll_periods')}
    if 'uq_period_company_month_year' not in existing_constraints:
        op.create_unique_constraint('uq_period_company_month_year', 'payroll_periods', ['company_id', 'period_month', 'period_year'])

    # Migrate data from pay_cycles to payroll_periods deterministically
    # Handles duplicate source cycles by ranking them by lifecycle progress and recency
    # Uses ON CONFLICT DO NOTHING to strictly preserve existing payroll periods and IDs
    if insp.has_table('pay_cycles'):
        op.execute("""
            WITH ranked_pay_cycles AS (
                SELECT 
                    pc.id,
                    pc.company_id,
                    pc.name,
                    COALESCE(pc.start_date, make_date(pc.period_year, pc.period_month, 1)) AS start_date,
                    COALESCE(pc.end_date, (make_date(pc.period_year, pc.period_month, 1) + interval '1 month - 1 day')::date) AS end_date,
                    COALESCE(pc.payment_date, pc.end_date, (make_date(pc.period_year, pc.period_month, 1) + interval '1 month - 1 day')::date) AS pay_date,
                    COALESCE(pc.processing_date, pc.end_date, (make_date(pc.period_year, pc.period_month, 1) + interval '1 month - 1 day')::date) AS processing_date,
                    COALESCE(pc.payment_date, pc.end_date, (make_date(pc.period_year, pc.period_month, 1) + interval '1 month - 1 day')::date) AS payment_date,
                    pc.period_month,
                    pc.period_year,
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
                    END AS status,
                    COALESCE(pc.is_locked, false) AS is_locked,
                    pc.locked_by,
                    pc.locked_at,
                    pc.remarks,
                    COALESCE(pc.created_at, now()) AS created_at,
                    COALESCE(pc.updated_at, now()) AS updated_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY pc.company_id, pc.period_month, pc.period_year
                        ORDER BY 
                            CASE pc.status
                                WHEN 'COMPLETED' THEN 7
                                WHEN 'PROCESSING' THEN 6
                                WHEN 'LOCKED' THEN 5
                                WHEN 'RUNNING' THEN 4
                                WHEN 'SCHEDULED' THEN 3
                                WHEN 'DRAFT' THEN 2
                                WHEN 'ARCHIVED' THEN 1
                                WHEN 'CANCELLED' THEN 0
                                ELSE 0
                            END DESC,
                            pc.is_locked DESC,
                            pc.updated_at DESC NULLS LAST,
                            pc.created_at DESC NULLS LAST,
                            pc.id DESC
                    ) AS rn
                FROM pay_cycles pc
                WHERE pc.company_id IS NOT NULL
                  AND pc.period_month IS NOT NULL
                  AND pc.period_year IS NOT NULL
                  AND pc.period_month BETWEEN 1 AND 12
            )
            INSERT INTO payroll_periods (
                id, company_id, name, start_date, end_date, pay_date, 
                processing_date, payment_date, period_month, period_year, 
                status, is_locked, locked_by, locked_at, remarks, created_at, updated_at
            )
            SELECT 
                rc.id, rc.company_id, rc.name, rc.start_date, rc.end_date, rc.pay_date,
                rc.processing_date, rc.payment_date, rc.period_month, rc.period_year,
                rc.status, rc.is_locked, rc.locked_by, rc.locked_at, rc.remarks, rc.created_at, rc.updated_at
            FROM ranked_pay_cycles rc
            WHERE rc.rn = 1
              AND NOT EXISTS (
                  SELECT 1 FROM payroll_periods pp 
                  WHERE pp.company_id = rc.company_id 
                    AND pp.period_month = rc.period_month 
                    AND pp.period_year = rc.period_year
              )
              AND NOT EXISTS (
                  SELECT 1 FROM payroll_periods pp
                  WHERE pp.id = rc.id
              )
            ON CONFLICT (company_id, period_month, period_year) DO NOTHING;
        """)

    # Set payment_date default to pay_date where null
    op.execute("UPDATE payroll_periods SET payment_date = pay_date WHERE payment_date IS NULL")
    # Set processing_date default to end_date where null
    op.execute("UPDATE payroll_periods SET processing_date = end_date WHERE processing_date IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Drop unique constraint if present
    existing_constraints = {c['name'] for c in insp.get_unique_constraints('payroll_periods')}
    if 'uq_period_company_month_year' in existing_constraints:
        op.drop_constraint('uq_period_company_month_year', 'payroll_periods', type_='unique')

    # Drop new columns if present
    existing_cols = {c['name'] for c in insp.get_columns('payroll_periods')}
    for col in ('locked_at', 'locked_by', 'is_locked', 'payment_date', 'processing_date'):
        if col in existing_cols:
            op.drop_column('payroll_periods', col)
    
    # Note: We don't delete migrated data in downgrade as it could be user data