"""analytics reports hardening and tenant scoping

Revision ID: e7d8c9b0a1f2
Revises: a9b8c7d6e5f4
Create Date: 2026-10-01 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7d8c9b0a1f2'
down_revision: Union[str, None] = 'a9b8c7d6e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add company_id and index to reports table
    op.add_column(
        'reports',
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=True)
    )
    op.create_index('ix_reports_company_id', 'reports', ['company_id'], unique=False)

    # 2. Add composite index on employees(company_id, joining_date) for fast headcount and tenure queries
    op.create_index(
        'ix_employees_company_joining',
        'employees',
        ['company_id', 'joining_date'],
        unique=False
    )

    # 3. Add composite index on employee_exits(company_id, last_working_date) for fast turnover queries
    op.create_index(
        'ix_employee_exits_company_date',
        'employee_exits',
        ['company_id', 'last_working_date'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_employee_exits_company_date', table_name='employee_exits')
    op.drop_index('ix_employees_company_joining', table_name='employees')
    op.drop_index('ix_reports_company_id', table_name='reports')
    op.drop_column('reports', 'company_id')
