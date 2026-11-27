"""add composite indexes for departments leaves employees

Revision ID: 5eacbae59559
Revises: 9bed212c8289
Create Date: 2026-11-27 10:34:20.288709

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5eacbae59559'
down_revision: Union[str, None] = '9bed212c8289'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_SPECS = (
    ("departments", "ix_departments_company_active_created", ["company_id", "is_deleted", "created_at"]),
    ("employees", "ix_employees_company_dept_status", ["company_id", "is_deleted", "status", "department_id"]),
    ("employees", "ix_employees_company_name_sort", ["company_id", "is_deleted", "first_name", "last_name"]),
    ("leave_requests", "ix_leave_requests_emp_sort", ["employee_id", "start_date", "created_at"]),
    ("leave_requests", "ix_leave_requests_status_sort", ["status", "start_date", "created_at"]),
)


def upgrade() -> None:
    """Create composite indexes to eliminate full table scans and in-memory sorts."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    existing_by_table: dict[str, set[str]] = {}
    for table_name, index_name, columns in _INDEX_SPECS:
        if table_name not in tables:
            continue
        if table_name not in existing_by_table:
            existing_by_table[table_name] = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name not in existing_by_table[table_name]:
            op.create_index(index_name, table_name, columns, unique=False)
            existing_by_table[table_name].add(index_name)


def downgrade() -> None:
    """Drop composite performance indexes if present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name, index_name, _ in reversed(_INDEX_SPECS):
        if table_name not in tables:
            continue
        existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)
