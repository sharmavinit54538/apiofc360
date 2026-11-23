"""Batch 4: real tenants, onboarding, e-sign, FnF and E5 migration.

Revision ID: 908a_batch4_onboarding_fnf
Revises: 907a_step4_statutory_forms
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "908a_batch4_onboarding_fnf"
down_revision = "907a_step4_statutory_forms"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _statutory_columns():
    return [
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("tan", sa.String(length=10), nullable=True),
        sa.Column("pf_code", sa.String(length=40), nullable=True),
        sa.Column("esi_code", sa.String(length=40), nullable=True),
        sa.Column("pt_reg_no", sa.String(length=50), nullable=True),
        sa.Column("lwf_reg_no", sa.String(length=50), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "legal_entities",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("manager_id", _uuid(), nullable=True),
        *_statutory_columns(),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_legal_entities_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["employees.id"], name=op.f("fk_legal_entities_manager_id_employees"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_entities")),
        sa.UniqueConstraint("company_id", "code", name="uq_legal_entities_company_code"),
    )
    op.create_table(
        "branches",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("legal_entity_id", _uuid(), nullable=False),
        sa.Column("branch_manager_id", _uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        *_statutory_columns(),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_branches_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["legal_entity_id"], ["legal_entities.id"], name=op.f("fk_branches_legal_entity_id_legal_entities"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_manager_id"], ["employees.id"], name=op.f("fk_branches_branch_manager_id_employees"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branches")),
        sa.UniqueConstraint("company_id", "code", name="uq_branches_company_code"),
    )
    op.add_column("employees", sa.Column("branch_id", _uuid(), nullable=True))
    op.add_column("employees", sa.Column("legal_entity_id", _uuid(), nullable=True))
    op.create_foreign_key("fk_employees_branch_id_branches", "employees", "branches", ["branch_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_employees_legal_entity_id_legal_entities", "employees", "legal_entities", ["legal_entity_id"], ["id"], ondelete="SET NULL")
    # This column pre-existed without a foreign key. Preserve legacy values:
    # PostgreSQL enforces the FK for new/updated rows while a later, explicit
    # branch backfill can make the historical values valid and validate it.
    op.create_foreign_key(
        "fk_departments_branch_id_branches", "departments", "branches",
        ["branch_id"], ["id"], ondelete="SET NULL", postgresql_not_valid=True,
    )

    for column in (
        sa.Column("offer_id", _uuid(), nullable=True),
        sa.Column("candidate_id", _uuid(), nullable=True),
        sa.Column("invite_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invite_token_hash", sa.String(length=64), nullable=True),
        sa.Column("bgv_status", sa.String(length=30), server_default="NOT_STARTED", nullable=False),
        sa.Column("bgv_provider_reference", sa.String(length=120), nullable=True),
        sa.Column("document_validation_json", sa.JSON(), nullable=True),
        sa.Column("completion_percentage", sa.Numeric(5, 2), server_default="0", nullable=False),
    ):
        op.add_column("employee_onboarding", column)
    op.create_foreign_key("fk_employee_onboarding_offer_id_offers", "employee_onboarding", "offers", ["offer_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_employee_onboarding_candidate_id_candidates", "employee_onboarding", "candidates", ["candidate_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_employee_onboarding_offer_id", "employee_onboarding", ["offer_id"], unique=False)
    op.create_table(
        "onboarding_task_checklists",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("employee_id", _uuid(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("task_key", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("owner_role", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("completed_by", _uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_onboarding_task_checklists_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name=op.f("fk_onboarding_task_checklists_employee_id_employees"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"], name=op.f("fk_onboarding_task_checklists_completed_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_onboarding_task_checklists")),
        sa.UniqueConstraint("employee_id", "task_key", name="uq_onboarding_task_employee_key"),
    )
    op.create_index("ix_onboarding_tasks_company_status", "onboarding_task_checklists", ["company_id", "status"], unique=False)

    for column in (
        sa.Column("ocr_status", sa.String(length=20), server_default="NOT_STARTED", nullable=False),
        sa.Column("ocr_extracted_json", sa.JSON(), nullable=True),
        sa.Column("ocr_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("ocr_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocr_error", sa.Text(), nullable=True),
    ):
        op.add_column("employee_documents", column)
    for column in (
        sa.Column("signed_pdf_hash", sa.String(length=64), nullable=True),
        sa.Column("signed_file_path", sa.String(length=500), nullable=True),
        sa.Column("provider", sa.String(length=20), server_default="BUILT_IN", nullable=False),
        sa.Column("provider_envelope_id", sa.String(length=120), nullable=True),
        sa.Column("signature_method", sa.String(length=30), nullable=True),
        sa.Column("signature_data", sa.Text(), nullable=True),
        sa.Column("otp_hash", sa.String(length=64), nullable=True),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requested_by", _uuid(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("request_ip", sa.String(length=45), nullable=True),
        sa.Column("webhook_payload_json", sa.JSON(), nullable=True),
        sa.Column("audit_certificate_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ):
        op.add_column("document_signatures", column)
    op.create_foreign_key("fk_document_signatures_requested_by_users", "document_signatures", "users", ["requested_by"], ["id"], ondelete="SET NULL")

    for column in (
        sa.Column("encashable", sa.Boolean(), nullable=True),
        sa.Column("encashable_days", sa.Numeric(6, 1), nullable=True),
        sa.Column("encashment_base", sa.String(length=10), server_default="BASIC", nullable=False),
        sa.Column("encashment_divisor", sa.Integer(), server_default="30", nullable=False),
    ):
        op.add_column("employee_leave_policies", column)
    for column in (
        sa.Column("notice_period_days_required", sa.Integer(), server_default="30", nullable=False),
        sa.Column("notice_period_days_served", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notice_shortfall_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notice_buyout", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notice_waived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("unpaid_salary_days", sa.Numeric(6, 2), nullable=True),
        sa.Column("fnf_status", sa.String(length=30), server_default="PENDING", nullable=False),
    ):
        op.add_column("employee_exits", column)
    for column in (
        sa.Column("status", sa.String(length=30), server_default="DRAFT", nullable=False),
        sa.Column("settlement_breakup", sa.JSON(), nullable=True),
        sa.Column("statement_path", sa.String(length=500), nullable=True),
        sa.Column("statement_hash", sa.String(length=64), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_letters_json", sa.JSON(), nullable=True),
    ):
        op.add_column("fnf_settlements", column)
    for column in (
        sa.Column("exit_id", _uuid(), nullable=True),
        sa.Column("notice_buyout", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notice_waived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_sheet_hash", sa.String(length=64), nullable=True),
        sa.Column("generated_letters_json", sa.JSON(), nullable=True),
    ):
        op.add_column("full_and_final_settlements", column)
    op.create_foreign_key("fk_full_and_final_settlements_exit_id_employee_exits", "full_and_final_settlements", "employee_exits", ["exit_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "leave_balances",
        sa.Column("id", _uuid(), nullable=False), sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("employee_id", _uuid(), nullable=False), sa.Column("leave_type", sa.String(length=50), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("allocated_days", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("used_days", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("carried_forward_days", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("balance_days", sa.Numeric(8, 2), nullable=True), sa.Column("encashable", sa.Boolean(), nullable=True),
        sa.Column("encashable_days", sa.Numeric(8, 2), nullable=True),
        sa.Column("encashment_base", sa.String(length=10), server_default="BASIC", nullable=False),
        sa.Column("encashment_divisor", sa.Integer(), server_default="30", nullable=False), *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_leave_balances_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name=op.f("fk_leave_balances_employee_id_employees"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_balances")),
        sa.UniqueConstraint("employee_id", "leave_type", "year", name="uq_leave_balances_employee_type_year"),
    )
    op.create_index("ix_leave_balances_company_employee", "leave_balances", ["company_id", "employee_id"], unique=False)
    op.create_table(
        "employee_ytd_salaries",
        sa.Column("id", _uuid(), nullable=False), sa.Column("employee_id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True), sa.Column("financial_year", sa.String(length=9), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False), sa.Column("period_year", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.BigInteger(), server_default="0", nullable=False) for name in (
            "gross_earnings_paise", "arrears_paise", "pf_paise", "esi_paise", "pt_paise", "lwf_paise",
            "tds_paise", "total_deductions_paise", "net_pay_paise",
        )],
        sa.Column("source", sa.String(length=30), server_default="MIGRATION", nullable=False),
        sa.Column("migration_batch_id", _uuid(), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_employee_ytd_salaries_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name=op.f("fk_employee_ytd_salaries_employee_id_employees"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employee_ytd_salaries")),
        sa.UniqueConstraint("employee_id", "period_month", "period_year", name="uq_employee_ytd_salary_period"),
    )
    op.create_index("ix_employee_ytd_company_fy", "employee_ytd_salaries", ["company_id", "financial_year"], unique=False)

    op.create_table(
        "data_migration_batches",
        sa.Column("id", _uuid(), nullable=False), sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("migration_type", sa.String(length=40), nullable=False), sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=False), sa.Column("status", sa.String(length=20), server_default="VALIDATED", nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False), sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_rows", sa.Integer(), server_default="0", nullable=False), sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("validation_errors_json", sa.JSON(), nullable=False), sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_reason", sa.Text(), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_data_migration_batches_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_data_migration_batches_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_migration_batches")),
    )
    op.create_index("ix_migration_batches_company_status", "data_migration_batches", ["company_id", "status"], unique=False)
    op.create_table(
        "data_migration_records",
        sa.Column("id", _uuid(), nullable=False), sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("batch_id", _uuid(), nullable=False), sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False), sa.Column("entity_id", _uuid(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False), sa.Column("before_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("after_snapshot_json", sa.JSON(), nullable=True), sa.Column("status", sa.String(length=20), server_default="COMMITTED", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True), *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_data_migration_records_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["data_migration_batches.id"], name=op.f("fk_data_migration_records_batch_id_data_migration_batches"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_migration_records")),
    )
    op.create_index("ix_migration_records_batch_row", "data_migration_records", ["batch_id", "row_number"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_migration_records_batch_row", table_name="data_migration_records")
    op.drop_table("data_migration_records")
    op.drop_index("ix_migration_batches_company_status", table_name="data_migration_batches")
    op.drop_table("data_migration_batches")
    op.drop_index("ix_employee_ytd_company_fy", table_name="employee_ytd_salaries")
    op.drop_table("employee_ytd_salaries")
    op.drop_index("ix_leave_balances_company_employee", table_name="leave_balances")
    op.drop_table("leave_balances")
    op.drop_constraint("fk_full_and_final_settlements_exit_id_employee_exits", "full_and_final_settlements", type_="foreignkey")
    for name in ("generated_letters_json", "settlement_sheet_hash", "settled_at", "notice_waived", "notice_buyout", "exit_id"):
        op.drop_column("full_and_final_settlements", name)
    for name in ("generated_letters_json", "settled_at", "statement_hash", "statement_path", "settlement_breakup", "status"):
        op.drop_column("fnf_settlements", name)
    for name in ("fnf_status", "unpaid_salary_days", "notice_waived", "notice_buyout", "notice_shortfall_days", "notice_period_days_served", "notice_period_days_required"):
        op.drop_column("employee_exits", name)
    for name in ("encashment_divisor", "encashment_base", "encashable_days", "encashable"):
        op.drop_column("employee_leave_policies", name)
    op.drop_constraint("fk_document_signatures_requested_by_users", "document_signatures", type_="foreignkey")
    for name in ("updated_at", "audit_certificate_json", "webhook_payload_json", "request_ip", "user_agent", "requested_by", "otp_attempts", "otp_expires_at", "otp_hash", "signature_data", "signature_method", "provider_envelope_id", "provider", "signed_file_path", "signed_pdf_hash"):
        op.drop_column("document_signatures", name)
    for name in ("ocr_error", "ocr_validated_at", "ocr_confidence", "ocr_extracted_json", "ocr_status"):
        op.drop_column("employee_documents", name)
    op.drop_index("ix_onboarding_tasks_company_status", table_name="onboarding_task_checklists")
    op.drop_table("onboarding_task_checklists")
    op.drop_index("ix_employee_onboarding_offer_id", table_name="employee_onboarding")
    op.drop_constraint("fk_employee_onboarding_candidate_id_candidates", "employee_onboarding", type_="foreignkey")
    op.drop_constraint("fk_employee_onboarding_offer_id_offers", "employee_onboarding", type_="foreignkey")
    for name in ("completion_percentage", "document_validation_json", "bgv_provider_reference", "bgv_status", "invite_token_hash", "invite_sent_at", "candidate_id", "offer_id"):
        op.drop_column("employee_onboarding", name)
    op.drop_constraint("fk_departments_branch_id_branches", "departments", type_="foreignkey")
    op.drop_constraint("fk_employees_legal_entity_id_legal_entities", "employees", type_="foreignkey")
    op.drop_constraint("fk_employees_branch_id_branches", "employees", type_="foreignkey")
    op.drop_column("employees", "legal_entity_id")
    op.drop_column("employees", "branch_id")
    op.drop_table("branches")
    op.drop_table("legal_entities")
