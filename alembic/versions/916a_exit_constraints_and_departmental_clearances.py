"""Add exit constraints and departmental clearances

Revision ID: 916a
Revises: 915a
Create Date: 2026-11-16

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "916a"
down_revision = "915a_payroll_processing_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create departmental_clearances table
    op.create_table(
        "departmental_clearances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text("gen_random_uuid()")),
        sa.Column("exit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee_exits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="PENDING"),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approver_name", sa.String(200), nullable=True),
        sa.Column("approver_role", sa.String(50), nullable=True),
        sa.Column("comments", sa.Text, nullable=True),
        sa.Column("evidence_reference", sa.String(500), nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_dept_clearance_exit_id", "departmental_clearances", ["exit_id"])
    op.create_index("ix_dept_clearance_department", "departmental_clearances", ["department"])
    op.create_index("ix_dept_clearance_approver_id", "departmental_clearances", ["approver_id"])
    op.create_index("ix_dept_clearance_status", "departmental_clearances", ["status"])
    
    # 2. Add partial unique index for one active exit per employee per tenant
    # Active = not COMPLETED, CANCELLED, MANAGER_REJECTED, HR_REJECTED
    op.execute("""
        CREATE UNIQUE INDEX ix_one_active_exit_per_employee
        ON employee_exits (employee_id)
        WHERE is_deleted = false
        AND status NOT IN ('COMPLETED', 'CANCELLED', 'MANAGER_REJECTED', 'HR_REJECTED', 'SETTLED')
    """)
    
    # 3. Add unique constraints for one-to-one per-exit records
    op.create_index("ix_kt_one_per_exit", "knowledge_transfers", ["exit_id"], unique=True)
    op.create_index("ix_clearance_one_per_exit", "clearance_requests", ["exit_id"], unique=True)
    op.create_index("ix_exit_interview_one_per_exit", "exit_interviews", ["exit_id"], unique=True)
    op.create_index("ix_fnf_one_per_exit", "fnf_settlements", ["exit_id"], unique=True)
    
    # 4. Add check constraint for valid exit statuses
    op.execute("""
        ALTER TABLE employee_exits
        ADD CONSTRAINT ck_employee_exits_status_valid
        CHECK (status IN (
            'DRAFT', 'SUBMITTED', 'PENDING_MANAGER_APPROVAL', 'MANAGER_APPROVED',
            'MANAGER_REJECTED', 'PENDING_HR_APPROVAL', 'HR_APPROVED', 'HR_REJECTED',
            'NOTICE_PERIOD', 'KNOWLEDGE_TRANSFER_PENDING', 'ASSET_RETURN_PENDING',
            'NO_DUES_PENDING', 'EXIT_INTERVIEW_PENDING', 'FNF_PENDING', 'FNF_FINALIZED',
            'SETTLED', 'COMPLETED', 'CANCELLED'
        ))
    """)
    
    # 5. Add check constraint for valid departmental clearance statuses
    op.execute("""
        ALTER TABLE departmental_clearances
        ADD CONSTRAINT ck_dept_clearance_status_valid
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'NOT_APPLICABLE'))
    """)
    
    # 6. Add check constraint for valid departmental clearance departments
    op.execute("""
        ALTER TABLE departmental_clearances
        ADD CONSTRAINT ck_dept_clearance_department_valid
        CHECK (department IN ('IT', 'HR', 'FINANCE', 'ADMIN', 'MANAGER', 'SECURITY'))
    """)
    
    # 7. Add check constraint for valid asset return statuses
    op.execute("""
        ALTER TABLE asset_returns
        ADD CONSTRAINT ck_asset_return_status_valid
        CHECK (return_status IN ('PENDING', 'RETURNED', 'NOT_APPLICABLE'))
    """)


def downgrade() -> None:
    # Drop check constraints
    op.execute("ALTER TABLE asset_returns DROP CONSTRAINT IF EXISTS ck_asset_return_status_valid")
    op.execute("ALTER TABLE departmental_clearances DROP CONSTRAINT IF EXISTS ck_dept_clearance_department_valid")
    op.execute("ALTER TABLE departmental_clearances DROP CONSTRAINT IF EXISTS ck_dept_clearance_status_valid")
    op.execute("ALTER TABLE employee_exits DROP CONSTRAINT IF EXISTS ck_employee_exits_status_valid")
    
    # Drop unique indexes
    op.drop_index("ix_fnf_one_per_exit", table_name="fnf_settlements")
    op.drop_index("ix_exit_interview_one_per_exit", table_name="exit_interviews")
    op.drop_index("ix_clearance_one_per_exit", table_name="clearance_requests")
    op.drop_index("ix_kt_one_per_exit", table_name="knowledge_transfers")
    
    # Drop partial unique index
    op.execute("DROP INDEX IF EXISTS ix_one_active_exit_per_employee")
    
    # Drop departmental_clearances table
    op.drop_index("ix_dept_clearance_status", table_name="departmental_clearances")
    op.drop_index("ix_dept_clearance_approver_id", table_name="departmental_clearances")
    op.drop_index("ix_dept_clearance_department", table_name="departmental_clearances")
    op.drop_index("ix_dept_clearance_exit_id", table_name="departmental_clearances")
    op.drop_table("departmental_clearances")