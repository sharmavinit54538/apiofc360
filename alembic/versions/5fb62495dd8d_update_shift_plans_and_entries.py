"""update_shift_plans_and_entries

Revision ID: 5fb62495dd8d
Revises: 260af0f72068
Create Date: 2026-10-12 08:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM
from sqlalchemy.sql import text


revision: str = '5fb62495dd8d'
down_revision: Union[str, None] = '260af0f72068'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add status, source, created_by, published_by, published_at, validation_report to shift_plans
    # Create ENUM types first
    op.execute(text("CREATE TYPE shift_plan_status AS ENUM ('DRAFT', 'PUBLISHED', 'ARCHIVED')"))
    op.execute(text("CREATE TYPE shift_plan_source AS ENUM ('AI', 'MANUAL')"))

    op.add_column('shift_plans', sa.Column('status', sa.Enum('DRAFT', 'PUBLISHED', 'ARCHIVED', name='shift_plan_status'), nullable=False, server_default='DRAFT'))
    op.add_column('shift_plans', sa.Column('source', sa.Enum('AI', 'MANUAL', name='shift_plan_source'), nullable=False, server_default='MANUAL'))
    op.add_column('shift_plans', sa.Column('created_by', UUID(as_uuid=True), nullable=True))
    op.add_column('shift_plans', sa.Column('published_by', UUID(as_uuid=True), nullable=True))
    op.add_column('shift_plans', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('shift_plans', sa.Column('validation_report', JSONB, nullable=True))

    # Add FKs
    op.create_foreign_key('fk_shift_plans_created_by', 'shift_plans', 'users', ['created_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_shift_plans_published_by', 'shift_plans', 'users', ['published_by'], ['id'], ondelete='SET NULL')

    # Add CHECK constraint
    op.create_check_constraint('ck_shift_plans_period', 'shift_plans', 'period_end >= period_start')

    # Backfill: mark existing plans as PUBLISHED
    conn.execute(text("UPDATE shift_plans SET status = 'PUBLISHED', source = 'MANUAL' WHERE status = 'DRAFT'"))

    # 2. Add columns to shift_plan_entries
    op.execute(text("CREATE TYPE shift_type_enum AS ENUM ('DAY', 'NIGHT', 'MORNING', 'EVENING', 'OVERTIME', 'ROTATION', 'HOLIDAY', 'OFF', 'WEEKLY_OFF', 'LEAVE', 'TRAINING', 'WFH')"))
    op.execute(text("CREATE TYPE entry_approval_status AS ENUM ('APPROVED', 'PENDING', 'REJECTED')"))

    op.add_column('shift_plan_entries', sa.Column('company_id', UUID(as_uuid=True), nullable=True))
    op.add_column('shift_plan_entries', sa.Column('shift_id', UUID(as_uuid=True), nullable=True))
    op.add_column('shift_plan_entries', sa.Column('approval_status', sa.Enum('APPROVED', 'PENDING', 'REJECTED', name='entry_approval_status'), nullable=False, server_default='APPROVED'))

    # Add FKs
    op.create_foreign_key('fk_shift_plan_entries_company_id', 'shift_plan_entries', 'companies', ['company_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_shift_plan_entries_shift_id', 'shift_plan_entries', 'shifts', ['shift_id'], ['id'], ondelete='SET NULL')

    # Backfill company_id from parent plan
    conn.execute(text("""
        UPDATE shift_plan_entries spe
        SET company_id = sp.company_id
        FROM shift_plans sp
        WHERE spe.plan_id = sp.id
    """))

    # Make company_id NOT NULL
    op.alter_column('shift_plan_entries', 'company_id', nullable=False)

    # Change shift_type to use ENUM
    # First convert existing string values to enum
    conn.execute(text("""
        UPDATE shift_plan_entries
        SET shift_type = upper(shift_type)
        WHERE shift_type IS NOT NULL
    """))

    # Create unique constraint
    op.create_unique_constraint('uq_shift_plan_entry_plan_emp_date', 'shift_plan_entries', ['plan_id', 'employee_id', 'shift_date'])

    # Create indexes
    op.create_index('ix_shift_plan_entries_plan_id', 'shift_plan_entries', ['plan_id'])
    op.create_index('ix_shift_plan_entries_employee_id', 'shift_plan_entries', ['employee_id'])
    op.create_index('ix_shift_plan_entries_shift_date', 'shift_plan_entries', ['shift_date'])
    op.create_index('ix_shift_plan_entries_company_id', 'shift_plan_entries', ['company_id'])
    op.create_index('ix_shift_plan_entries_approval', 'shift_plan_entries', ['approval_status'])

    # 3. Create a MANUAL plan per company/month (lazily in service, but we can seed here)
    # This is optional - the service will create it on demand


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_shift_plan_entries_approval', table_name='shift_plan_entries')
    op.drop_index('ix_shift_plan_entries_company_id', table_name='shift_plan_entries')
    op.drop_index('ix_shift_plan_entries_shift_date', table_name='shift_plan_entries')
    op.drop_index('ix_shift_plan_entries_employee_id', table_name='shift_plan_entries')
    op.drop_index('ix_shift_plan_entries_plan_id', table_name='shift_plan_entries')

    # Drop unique constraint
    op.drop_constraint('uq_shift_plan_entry_plan_emp_date', 'shift_plan_entries', type_='unique')

    # Drop FKs
    op.drop_constraint('fk_shift_plan_entries_shift_id', 'shift_plan_entries', type_='foreignkey')
    op.drop_constraint('fk_shift_plan_entries_company_id', 'shift_plan_entries', type_='foreignkey')

    # Drop columns from shift_plan_entries
    op.drop_column('shift_plan_entries', 'approval_status')
    op.drop_column('shift_plan_entries', 'shift_id')
    op.drop_column('shift_plan_entries', 'company_id')

    # Drop ENUM types for entries
    op.execute(text("DROP TYPE IF EXISTS entry_approval_status"))
    op.execute(text("DROP TYPE IF EXISTS shift_type_enum"))

    # Drop FKs from shift_plans
    op.drop_constraint('fk_shift_plans_published_by', 'shift_plans', type_='foreignkey')
    op.drop_constraint('fk_shift_plans_created_by', 'shift_plans', type_='foreignkey')

    # Drop CHECK constraint
    op.drop_constraint('ck_shift_plans_period', 'shift_plans', type_='check')

    # Drop columns from shift_plans
    op.drop_column('shift_plans', 'validation_report')
    op.drop_column('shift_plans', 'published_at')
    op.drop_column('shift_plans', 'published_by')
    op.drop_column('shift_plans', 'created_by')
    op.drop_column('shift_plans', 'source')
    op.drop_column('shift_plans', 'status')

    # Drop ENUM types for plans
    op.execute(text("DROP TYPE IF EXISTS shift_plan_source"))
    op.execute(text("DROP TYPE IF EXISTS shift_plan_status"))