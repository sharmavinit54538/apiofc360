"""Step 3 batch 1: attendance locks, arrears, OT allowances and comparisons.

Revision ID: 906a_step3_lock_arrears_ot
Revises: 905a_dpdp_field_encryption
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "906a_step3_lock_arrears_ot"
down_revision = "905a_dpdp_field_encryption"
branch_labels = None
depends_on = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # Also protect upgrades from databases whose current revision is already 905a.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")

    for table in ("payroll_periods", "pay_cycles"):
        op.add_column(table, sa.Column("regularisation_deadline", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("attendance_locked_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("attendance_locked_by", _uuid(), nullable=True))
        op.add_column(table, sa.Column("unlock_reason", sa.Text(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_attendance_locked_by_users",
            table,
            "users",
            ["attendance_locked_by"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column("variable_inputs", sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("variable_inputs", sa.Column("source", sa.String(length=50), nullable=True))
    op.add_column("overtime_policies", sa.Column("rate_base", sa.String(length=20), nullable=False, server_default="BASIC"))

    op.create_table(
        "shift_allowance_policies",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("shift_id", _uuid(), sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("shift_type", sa.String(length=30), nullable=False, server_default="GENERAL"),
        sa.Column("allowance_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("is_esi_applicable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_pf_applicable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_taxable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_shift_allowance_company_type", "shift_allowance_policies", ["company_id", "shift_type"])
    op.create_index("ix_shift_allowance_shift", "shift_allowance_policies", ["shift_id"])

    op.create_table(
        "comp_off_ledgers",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("employee_id", _uuid(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("worked_date", sa.Date(), nullable=False),
        sa.Column("worked_hours", sa.Numeric(7, 2), nullable=False, server_default="0"),
        sa.Column("credit_days", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="EARNED"),
        sa.Column("encashment_amount_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("encashed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_comp_off_company_employee", "comp_off_ledgers", ["company_id", "employee_id"])
    op.create_index("ix_comp_off_status_expiry", "comp_off_ledgers", ["status", "expiry_date"])

    op.create_table(
        "arrear_ledgers",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("employee_id", _uuid(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_period_id", _uuid(), sa.ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_period_id", _uuid(), sa.ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("delta_days", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("calculation_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("applied_run_id", _uuid(), sa.ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_arrear_ledgers_company_employee", "arrear_ledgers", ["company_id", "employee_id"])
    op.create_index("ix_arrear_ledgers_target_status", "arrear_ledgers", ["target_period_id", "status"])
    op.create_index("ix_arrear_ledgers_source_period", "arrear_ledgers", ["source_period_id"])

    op.create_table(
        "parallel_payroll_comparison_reports",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("run_id", _uuid(), sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legacy_file_name", sa.String(length=255), nullable=True),
        sa.Column("legacy_file_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="COMPLETED"),
        sa.Column("employee_variances", sa.JSON(), nullable=False),
        sa.Column("head_variances", sa.JSON(), nullable=False),
        sa.Column("diagnoses", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_by", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_parallel_payroll_reports_run", "parallel_payroll_comparison_reports", ["run_id"])
    op.create_index("ix_parallel_payroll_reports_company", "parallel_payroll_comparison_reports", ["company_id", "created_at"])

    # Permission definitions are idempotent so a tenant can map them to its own
    # roles without a destructive RBAC migration.
    op.execute(
        """
        INSERT INTO security_permissions
            (id, module_name, action_name, permission_code, description)
        VALUES
            ('906a0000-0000-0000-0000-000000000001', 'PAYROLL', 'LOCK_ATTENDANCE', 'payroll:lock_attendance', 'Lock attendance for a payroll period'),
            ('906a0000-0000-0000-0000-000000000002', 'PAYROLL', 'UNLOCK_ATTENDANCE', 'payroll:unlock_attendance', 'Unlock attendance with a mandatory audit reason')
        ON CONFLICT (permission_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM security_permissions WHERE permission_code IN ('payroll:lock_attendance', 'payroll:unlock_attendance')")
    op.drop_index("ix_parallel_payroll_reports_company", table_name="parallel_payroll_comparison_reports")
    op.drop_index("ix_parallel_payroll_reports_run", table_name="parallel_payroll_comparison_reports")
    op.drop_table("parallel_payroll_comparison_reports")
    op.drop_index("ix_arrear_ledgers_source_period", table_name="arrear_ledgers")
    op.drop_index("ix_arrear_ledgers_target_status", table_name="arrear_ledgers")
    op.drop_index("ix_arrear_ledgers_company_employee", table_name="arrear_ledgers")
    op.drop_table("arrear_ledgers")
    op.drop_index("ix_comp_off_status_expiry", table_name="comp_off_ledgers")
    op.drop_index("ix_comp_off_company_employee", table_name="comp_off_ledgers")
    op.drop_table("comp_off_ledgers")
    op.drop_index("ix_shift_allowance_shift", table_name="shift_allowance_policies")
    op.drop_index("ix_shift_allowance_company_type", table_name="shift_allowance_policies")
    op.drop_table("shift_allowance_policies")
    op.drop_column("overtime_policies", "rate_base")
    op.drop_column("variable_inputs", "source")
    op.drop_column("variable_inputs", "is_locked")
    for table in ("pay_cycles", "payroll_periods"):
        op.drop_constraint(f"fk_{table}_attendance_locked_by_users", table, type_="foreignkey")
        op.drop_column(table, "unlock_reason")
        op.drop_column(table, "attendance_locked_by")
        op.drop_column(table, "attendance_locked_at")
        op.drop_column(table, "regularisation_deadline")
