"""Add HR-initiated exit fields

Revision ID: 918a
Revises: 917a
Create Date: 2026-11-16

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "918a"
down_revision = "917a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add HR-initiated exit fields
    op.add_column("employee_exits", sa.Column("exit_type", sa.String(30), nullable=False, server_default="resignation"))
    op.add_column("employee_exits", sa.Column("effective_date", sa.Date, nullable=True))
    op.add_column("employee_exits", sa.Column("initiated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("employee_exits", sa.Column("initiated_by_role", sa.String(50), nullable=True))
    
    # Create index on exit_type
    op.create_index("ix_employee_exits_exit_type", "employee_exits", ["exit_type"])
    op.create_index("ix_employee_exits_initiated_by", "employee_exits", ["initiated_by"])
    
    # Add check constraint for valid exit types
    op.execute("""
        ALTER TABLE employee_exits
        ADD CONSTRAINT ck_employee_exits_exit_type_valid
        CHECK (exit_type IN (
            'resignation', 'termination', 'retirement', 'contract_end',
            'layoff', 'mutual_separation', 'probation_failure',
            'medical_separation', 'death'
        ))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE employee_exits DROP CONSTRAINT IF EXISTS ck_employee_exits_exit_type_valid")
    op.drop_index("ix_employee_exits_initiated_by", table_name="employee_exits")
    op.drop_index("ix_employee_exits_exit_type", table_name="employee_exits")
    op.drop_column("employee_exits", "initiated_by_role")
    op.drop_column("employee_exits", "initiated_by")
    op.drop_column("employee_exits", "effective_date")
    op.drop_column("employee_exits", "exit_type")