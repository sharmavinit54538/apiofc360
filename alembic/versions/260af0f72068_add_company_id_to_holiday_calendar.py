"""add_company_id_to_holiday_calendar

Revision ID: 260af0f72068
Revises: 19eded85252d
Create Date: 2026-10-12 08:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text


revision: str = '260af0f72068'
down_revision: Union[str, None] = '19eded85252d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add company_id column (nullable first)
    op.add_column('holiday_calendar', sa.Column('company_id', UUID(as_uuid=True), nullable=True))

    # 2. Backfill: clone existing holidays to each company
    conn = op.get_bind()

    # Get all companies
    companies = conn.execute(text("SELECT id FROM companies")).fetchall()

    # Get existing global holidays (no company_id)
    global_holidays = conn.execute(text("""
        SELECT holiday_name, holiday_date, holiday_type, branch, description, is_recurring, created_at
        FROM holiday_calendar
        WHERE company_id IS NULL
    """)).fetchall()

    # Clone each holiday for each company
    for company in companies:
        company_id = str(company.id)
        for holiday in global_holidays:
            conn.execute(text("""
                INSERT INTO holiday_calendar (id, company_id, holiday_name, holiday_date, holiday_type, branch, description, is_recurring, created_at)
                VALUES (gen_random_uuid(), :cid, :name, :date, :type, :branch, :desc, :recurring, :created)
            """), {
                "cid": company_id,
                "name": holiday.holiday_name,
                "date": holiday.holiday_date,
                "type": holiday.holiday_type,
                "branch": holiday.branch,
                "desc": holiday.description,
                "recurring": holiday.is_recurring,
                "created": holiday.created_at,
            })

    # 3. Delete original global holidays
    conn.execute(text("DELETE FROM holiday_calendar WHERE company_id IS NULL"))

    # 4. Make company_id NOT NULL and add FK
    op.alter_column('holiday_calendar', 'company_id', nullable=False)
    op.create_foreign_key('fk_holiday_calendar_company_id', 'holiday_calendar', 'companies', ['company_id'], ['id'], ondelete='CASCADE')

    # 5. Add unique constraint and indexes
    op.create_unique_constraint('uq_holiday_company_date_branch', 'holiday_calendar', ['company_id', 'holiday_date', 'branch'])
    op.create_index('ix_holiday_company_date', 'holiday_calendar', ['company_id', 'holiday_date'])
    op.create_index('ix_holiday_company_id', 'holiday_calendar', ['company_id'])


def downgrade() -> None:
    # Drop constraints and indexes
    op.drop_constraint('uq_holiday_company_date_branch', 'holiday_calendar', type_='unique')
    op.drop_index('ix_holiday_company_date', table_name='holiday_calendar')
    op.drop_index('ix_holiday_company_id', table_name='holiday_calendar')
    op.drop_constraint('fk_holiday_calendar_company_id', 'holiday_calendar', type_='foreignkey')

    # Re-create global holidays (one copy per unique holiday)
    conn = op.get_bind()

    # Get distinct holidays across all companies
    distinct_holidays = conn.execute(text("""
        SELECT DISTINCT ON (holiday_name, holiday_date, holiday_type, branch)
            holiday_name, holiday_date, holiday_type, branch, description, is_recurring, MIN(created_at) as created_at
        FROM holiday_calendar
        GROUP BY holiday_name, holiday_date, holiday_type, branch, description, is_recurring
    """)).fetchall()

    # Insert back as global (no company_id)
    for holiday in distinct_holidays:
        conn.execute(text("""
            INSERT INTO holiday_calendar (id, holiday_name, holiday_date, holiday_type, branch, description, is_recurring, created_at)
            VALUES (gen_random_uuid(), :name, :date, :type, :branch, :desc, :recurring, :created)
        """), {
            "name": holiday.holiday_name,
            "date": holiday.holiday_date,
            "type": holiday.holiday_type,
            "branch": holiday.branch,
            "desc": holiday.description,
            "recurring": holiday.is_recurring,
            "created": holiday.created_at,
        })

    # Delete company-specific holidays
    conn.execute(text("DELETE FROM holiday_calendar WHERE company_id IS NOT NULL"))

    # Make company_id nullable again (or drop it)
    op.alter_column('holiday_calendar', 'company_id', nullable=True)