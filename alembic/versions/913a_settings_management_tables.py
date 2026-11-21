"""Create settings management tables for employee, leave, document, and asset configurations.

Revision ID: 913a_settings_management
Revises: 912a_expense_workflow
Create Date: 2026-11-14 10:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "913a_settings_management"
down_revision = "912a_expense_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Employee Settings
    op.create_table(
        "employee_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("employee_id_prefix", sa.String(20), nullable=False, server_default=sa.text("'EMP'")),
        sa.Column("employee_id_start_number", sa.Integer(), nullable=False, server_default=sa.text("1001")),
        sa.Column("probation_period_days", sa.Integer(), nullable=False, server_default=sa.text("90")),
        sa.Column("default_employment_type", sa.String(50), nullable=False, server_default=sa.text("'full_time'")),
        sa.Column("default_employee_status", sa.String(50), nullable=False, server_default=sa.text("'active'")),
        sa.Column("allow_employee_profile_edit", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("require_manager_assignment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", name="uq_employee_settings_company_id"),
    )
    op.create_index("ix_employee_settings_company_id", "employee_settings", ["company_id"])

    # 2. Leave Settings
    op.create_table(
        "leave_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("leave_year_start_month", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("allow_half_day_leave", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allow_negative_balance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("require_manager_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_consecutive_leave_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("carry_forward_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("carry_forward_limit", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("leave_encashment_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", name="uq_leave_settings_company_id"),
    )
    op.create_index("ix_leave_settings_company_id", "leave_settings", ["company_id"])

    # 3. Document Settings
    op.create_table(
        "document_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "allowed_file_types",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"pdf\", \"jpg\", \"jpeg\", \"png\"]'"),
        ),
        sa.Column("max_file_size_mb", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("require_document_verification", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("document_expiry_alert_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("employee_can_upload_documents", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("manager_can_view_documents", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", name="uq_document_settings_company_id"),
    )
    op.create_index("ix_document_settings_company_id", "document_settings", ["company_id"])

    # 4. Asset Settings
    op.create_table(
        "asset_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("asset_id_prefix", sa.String(20), nullable=False, server_default=sa.text("'AST'")),
        sa.Column("require_assignment_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("enable_asset_return_tracking", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("enable_asset_condition_tracking", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("enable_warranty_reminders", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("warranty_reminder_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("enable_asset_depreciation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", name="uq_asset_settings_company_id"),
    )
    op.create_index("ix_asset_settings_company_id", "asset_settings", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_asset_settings_company_id", table_name="asset_settings")
    op.drop_table("asset_settings")

    op.drop_index("ix_document_settings_company_id", table_name="document_settings")
    op.drop_table("document_settings")

    op.drop_index("ix_leave_settings_company_id", table_name="leave_settings")
    op.drop_table("leave_settings")

    op.drop_index("ix_employee_settings_company_id", table_name="employee_settings")
    op.drop_table("employee_settings")
