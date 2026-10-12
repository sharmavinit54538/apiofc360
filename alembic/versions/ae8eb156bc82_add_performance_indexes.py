"""add_performance_indexes

Revision ID: ae8eb156bc82
Revises: 9dbecb1de6de
Create Date: 2026-10-12 17:14:40.421732

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ae8eb156bc82'
down_revision: Union[str, None] = '9dbecb1de6de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Attendance indexes for analytics queries
    # Composite index for company + date (attendance analytics)
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_attendances_company_date ON attendances (company_id, date)")
    
    # Composite index for company + employee + date (personal history queries)
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_attendances_company_employee_date ON attendances (company_id, employee_id, date)")
    
    # Partial index for open check-ins (check_out_time IS NULL)
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_attendances_open_checkin ON attendances (employee_id) WHERE check_out_time IS NULL")
    
    # Employee indexes - remove redundant single-column indexes covered by composites
    # The following composites already cover company_id, status, department, is_deleted:
    # ix_employees_company_status (company_id, status, is_deleted)
    # ix_employees_company_department (company_id, department, is_deleted)
    
    # Drop redundant single-column indexes on employees (if they exist)
    # Using DROP INDEX CONCURRENTLY to avoid locking
    for idx in [
        "ix_employees_company_id",
        "ix_employees_status", 
        "ix_employees_department",
        "ix_employees_is_deleted",
    ]:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {idx}")
    
    # Notification indexes for unread count queries
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_user_unread_created ON user_notifications (recipient_id, is_read, created_at DESC)")
    
    # Leave requests indexes
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_leave_requests_company_status_start ON leave_requests (company_id, status, start_date)")
    
    # Audit logs indexes
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_logs_company_created ON audit_logs (company_id, created_at DESC)")


def downgrade() -> None:
    # Re-create the dropped indexes
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_employees_company_id ON employees (company_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_employees_status ON employees (status)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_employees_department ON employees (department)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_employees_is_deleted ON employees (is_deleted)")
    
    # Drop the new indexes
    for idx in [
        "ix_attendances_company_date",
        "ix_attendances_company_employee_date",
        "ix_attendances_open_checkin",
        "ix_notifications_user_unread_created",
        "ix_leave_requests_company_status_start",
        "ix_audit_logs_company_created",
    ]:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {idx}")