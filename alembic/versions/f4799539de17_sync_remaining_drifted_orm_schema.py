"""sync remaining drifted orm schema

Revision ID: f4799539de17
Revises: 5eacbae59559
Create Date: 2026-11-27 11:42:53.404102

Safely aligns PostgreSQL schema with SQLAlchemy ORM models without dropping
tables or mutating existing business records. Idempotent on both live drifted
databases and fresh `base -> head` installations.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f4799539de17"
down_revision: Union[str, None] = "5eacbae59559"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(insp, table: str) -> dict[str, dict]:
    return {c["name"]: c for c in insp.get_columns(table, schema="public")}


def _idxs(insp, table: str) -> set[str]:
    return {i["name"] for i in insp.get_indexes(table, schema="public") if i.get("name")}


def _fks(insp, table: str) -> tuple[set[str], set[tuple]]:
    fks = insp.get_foreign_keys(table, schema="public")
    names = {fk["name"] for fk in fks if fk.get("name")}
    sigs = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
        for fk in fks
    }
    return names, sigs


def _add_missing_columns(bind, table: str, specs: list[tuple[str, sa.Column]]) -> None:
    insp = sa.inspect(bind)
    existing = _cols(insp, table)
    for col_name, col_def in specs:
        if col_name not in existing:
            op.add_column(table, col_def)


def _create_missing_indexes(
    bind,
    specs: list[tuple[str, str, list[str], bool]],
) -> None:
    insp = sa.inspect(bind)
    cache: dict[str, set[str]] = {}
    for idx_name, table, cols, unique in specs:
        existing = cache.setdefault(table, _idxs(insp, table))
        if idx_name not in existing:
            op.create_index(idx_name, table, cols, unique=unique)
            existing.add(idx_name)


def _create_missing_fks(
    bind,
    specs: list[tuple[str, str, str, list[str], list[str], str | None]],
) -> None:
    insp = sa.inspect(bind)
    cache: dict[str, tuple[set[str], set[tuple]]] = {}
    for fk_name, src_tbl, ref_tbl, local_cols, remote_cols, ondelete in specs:
        names, sigs = cache.setdefault(src_tbl, _fks(insp, src_tbl))
        sig = (tuple(local_cols), ref_tbl, tuple(remote_cols))
        if fk_name not in names and sig not in sigs:
            op.create_foreign_key(
                fk_name,
                src_tbl,
                ref_tbl,
                local_cols,
                remote_cols,
                ondelete=ondelete,
            )
            names.add(fk_name)
            sigs.add(sig)


# All 81 drifted columns grouped by table with exact ORM types & non-destructive defaults
_DRIFTED_COLUMNS: dict[str, list[tuple[str, sa.Column]]] = {
    "ai_messages": [
        ("message_metadata", sa.Column("message_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True)),
    ],
    "company_policy_documents": [
        ("version_number", sa.Column("version_number", sa.String(20), nullable=False, server_default=sa.text("'1.0'"))),
        ("effective_date", sa.Column("effective_date", sa.Date(), nullable=True)),
        ("supersedes_policy_id", sa.Column("supersedes_policy_id", postgresql.UUID(as_uuid=True), nullable=True)),
        ("status", sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'DRAFT'"))),
        ("acknowledgement_required", sa.Column("acknowledgement_required", sa.Boolean(), nullable=False, server_default=sa.text("true"))),
        ("acknowledgement_due_date", sa.Column("acknowledgement_due_date", sa.Date(), nullable=True)),
        ("reminder_after_days", sa.Column("reminder_after_days", sa.Integer(), nullable=False, server_default=sa.text("3"))),
        ("escalation_after_days", sa.Column("escalation_after_days", sa.Integer(), nullable=False, server_default=sa.text("7"))),
        ("target_branch_ids", sa.Column("target_branch_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("target_departments", sa.Column("target_departments", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("target_roles", sa.Column("target_roles", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("target_employment_types", sa.Column("target_employment_types", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())),
    ],
    "document_signatures": [
        ("signed_pdf_hash", sa.Column("signed_pdf_hash", sa.String(64), nullable=True)),
        ("signed_file_path", sa.Column("signed_file_path", sa.String(500), nullable=True)),
        ("provider", sa.Column("provider", sa.String(20), nullable=False, server_default=sa.text("'BUILT_IN'"))),
        ("provider_envelope_id", sa.Column("provider_envelope_id", sa.String(120), nullable=True)),
        ("signature_method", sa.Column("signature_method", sa.String(30), nullable=True)),
        ("signature_data", sa.Column("signature_data", sa.Text(), nullable=True)),
        ("otp_hash", sa.Column("otp_hash", sa.String(64), nullable=True)),
        ("otp_expires_at", sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True)),
        ("otp_attempts", sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default=sa.text("0"))),
        ("requested_by", sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("user_agent", sa.Column("user_agent", sa.String(500), nullable=True)),
        ("request_ip", sa.Column("request_ip", sa.String(45), nullable=True)),
        ("webhook_payload_json", sa.Column("webhook_payload_json", sa.JSON(), nullable=True)),
        ("audit_certificate_json", sa.Column("audit_certificate_json", sa.JSON(), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())),
    ],
    "employee_documents": [
        ("ocr_status", sa.Column("ocr_status", sa.String(20), nullable=False, server_default=sa.text("'NOT_STARTED'"))),
        ("ocr_extracted_json", sa.Column("ocr_extracted_json", sa.JSON(), nullable=True)),
        ("ocr_confidence", sa.Column("ocr_confidence", sa.Numeric(5, 4), nullable=True)),
        ("ocr_validated_at", sa.Column("ocr_validated_at", sa.DateTime(timezone=True), nullable=True)),
        ("ocr_error", sa.Column("ocr_error", sa.Text(), nullable=True)),
    ],
    "employee_onboarding": [
        ("offer_id", sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=True)),
        ("candidate_id", sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True)),
        ("invite_sent_at", sa.Column("invite_sent_at", sa.DateTime(timezone=True), nullable=True)),
        ("invite_token_hash", sa.Column("invite_token_hash", sa.String(64), nullable=True)),
        ("bgv_status", sa.Column("bgv_status", sa.String(30), nullable=False, server_default=sa.text("'NOT_STARTED'"))),
        ("bgv_provider_reference", sa.Column("bgv_provider_reference", sa.String(120), nullable=True)),
        ("document_validation_json", sa.Column("document_validation_json", sa.JSON(), nullable=True)),
        ("completion_percentage", sa.Column("completion_percentage", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0"))),
    ],
    "employee_policy_acceptances": [
        ("policy_document_id", sa.Column("policy_document_id", postgresql.UUID(as_uuid=True), nullable=True)),
        ("user_agent", sa.Column("user_agent", sa.String(500), nullable=True)),
        ("signature_hash", sa.Column("signature_hash", sa.String(64), nullable=True)),
        ("request_id", sa.Column("request_id", sa.String(100), nullable=True)),
    ],
    "employee_tax_info": [
        ("proof_status", sa.Column("proof_status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'"))),
        ("proof_cutoff_date", sa.Column("proof_cutoff_date", sa.Date(), nullable=True)),
        ("use_verified_declarations", sa.Column("use_verified_declarations", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
        ("declared_details_json", sa.Column("declared_details_json", sa.JSON(), nullable=True)),
        ("verified_details_json", sa.Column("verified_details_json", sa.JSON(), nullable=True)),
        ("previous_employer_income_paise", sa.Column("previous_employer_income_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("previous_employer_tds_paise", sa.Column("previous_employer_tds_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("ytd_tds_paise", sa.Column("ytd_tds_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("one_time_bonus_paise", sa.Column("one_time_bonus_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("variable_pay_paise", sa.Column("variable_pay_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("proof_submitted_at", sa.Column("proof_submitted_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_verified_at", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_verified_by", sa.Column("last_verified_by", postgresql.UUID(as_uuid=True), nullable=True)),
    ],
    "overtime_policies": [
        ("rate_base", sa.Column("rate_base", sa.String(20), nullable=False, server_default=sa.text("'BASIC'"))),
    ],
    "payroll_compliance_challans": [
        ("crn_number", sa.Column("crn_number", sa.String(100), nullable=True)),
        ("bank_reference", sa.Column("bank_reference", sa.String(150), nullable=True)),
        ("bsr_code", sa.Column("bsr_code", sa.String(20), nullable=True)),
        ("challan_serial_number", sa.Column("challan_serial_number", sa.String(50), nullable=True)),
    ],
    "reimbursement_claims": [
        ("currency", sa.Column("currency", sa.String(3), nullable=False, server_default=sa.text("'INR'"))),
        ("merchant", sa.Column("merchant", sa.String(255), nullable=True)),
        ("project_id", sa.Column("project_id", sa.String(100), nullable=True)),
        ("reviewed_by", sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("reviewed_at", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)),
        ("payment_reference", sa.Column("payment_reference", sa.String(128), nullable=True)),
        ("payment_method", sa.Column("payment_method", sa.String(32), nullable=True)),
        ("paid_at", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True)),
        ("paid_by", sa.Column("paid_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("deleted_at", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)),
    ],
    "tax_declaration_proofs": [
        ("verified_amount", sa.Column("verified_amount", sa.Numeric(14, 2), nullable=True)),
        ("status", sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'"))),
        ("verified_by", sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("verified_at", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True)),
        ("rejection_reason", sa.Column("rejection_reason", sa.String(500), nullable=True)),
        ("document_hash", sa.Column("document_hash", sa.String(64), nullable=True)),
        ("file_path", sa.Column("file_path", sa.String(500), nullable=True)),
    ],
}

_INDEX_SPECS: list[tuple[str, str, list[str], bool]] = [
    ("ix_employee_onboarding_offer_id", "employee_onboarding", ["offer_id"], False),
    ("ix_payroll_audit_logs_company_entity", "payroll_audit_logs", ["company_id", "entity_type", "entity_id", "created_at"], False),
    ("ix_payroll_compliance_challans_trrn", "payroll_compliance_challans", ["trrn_number"], False),
    ("ix_payroll_compliance_challans_company", "payroll_compliance_challans", ["company_id", "period_year", "period_month"], False),
    ("ix_reimbursement_claims_company_employee", "reimbursement_claims", ["company_id", "employee_id", "created_at"], False),
    ("ix_reimbursement_claims_company_payment", "reimbursement_claims", ["company_id", "payment_reference"], False),
    ("ix_reimbursement_claims_company_status_date", "reimbursement_claims", ["company_id", "status", "claim_date"], False),
    ("ix_shift_plans_status", "shift_plans", ["status"], False),
    # Performance indexes for hierarchy, attendance team reporting, employee _with_relations(), and asset listing
    ("ix_employees_reporting_manager_id", "employees", ["reporting_manager_id"], False),
    ("ix_assets_employee_id", "assets", ["employee_id"], False),
    ("ix_assets_company_active_created", "assets", ["company_id", "is_deleted", "created_at"], False),
]

_FK_SPECS: list[tuple[str, str, str, list[str], list[str], str | None]] = [
    ("fk_company_policy_documents_supersedes_policy_id", "company_policy_documents", "company_policy_documents", ["supersedes_policy_id"], ["id"], "SET NULL"),
    ("fk_departments_branch_id_branches", "departments", "branches", ["branch_id"], ["id"], "SET NULL"),
    ("fk_document_signatures_requested_by_users", "document_signatures", "users", ["requested_by"], ["id"], "SET NULL"),
    ("fk_employee_onboarding_candidate_id_candidates", "employee_onboarding", "candidates", ["candidate_id"], ["id"], "SET NULL"),
    ("fk_employee_onboarding_offer_id_offers", "employee_onboarding", "offers", ["offer_id"], ["id"], "SET NULL"),
    ("fk_employee_policy_acceptances_policy_document_id", "employee_policy_acceptances", "company_policy_documents", ["policy_document_id"], ["id"], "CASCADE"),
    ("fk_employee_tax_info_last_verified_by_users", "employee_tax_info", "users", ["last_verified_by"], ["id"], "SET NULL"),
    ("fk_full_and_final_settlements_exit_id_employee_exits", "full_and_final_settlements", "employee_exits", ["exit_id"], ["id"], "SET NULL"),
    ("fk_full_and_final_settlements_processed_by_users", "full_and_final_settlements", "users", ["processed_by"], ["id"], "SET NULL"),
    ("fk_full_and_final_settlements_created_by_users", "full_and_final_settlements", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_pay_cycles_attendance_locked_by_users", "pay_cycles", "users", ["attendance_locked_by"], ["id"], "SET NULL"),
    ("fk_payment_batch_items_repayout_batch_id", "payment_batch_items", "payment_batches", ["repayout_batch_id"], ["id"], "SET NULL"),
    ("fk_payment_batch_items_retry_source_item_id", "payment_batch_items", "payment_batch_items", ["retry_source_item_id"], ["id"], "RESTRICT"),
    ("fk_payment_batches_created_by_users", "payment_batches", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_payment_batches_retry_of_batch_id", "payment_batches", "payment_batches", ["retry_of_batch_id"], ["id"], "SET NULL"),
    ("fk_payment_batches_processed_by_users", "payment_batches", "users", ["processed_by"], ["id"], "SET NULL"),
    ("fk_payroll_periods_legal_entity_id", "payroll_periods", "legal_entities", ["legal_entity_id"], ["id"], "RESTRICT"),
    ("fk_payroll_periods_locked_by_users", "payroll_periods", "users", ["locked_by"], ["id"], "SET NULL"),
    ("fk_payroll_periods_attendance_locked_by_users", "payroll_periods", "users", ["attendance_locked_by"], ["id"], "SET NULL"),
    ("fk_payroll_runs_legal_entity_id", "payroll_runs", "legal_entities", ["legal_entity_id"], ["id"], "RESTRICT"),
    ("fk_payroll_runs_processed_by_users", "payroll_runs", "users", ["processed_by"], ["id"], "SET NULL"),
    ("fk_payroll_runs_created_by_users", "payroll_runs", "users", ["created_by"], ["id"], "SET NULL"),
    ("fk_reimbursement_claims_reviewed_by_users", "reimbursement_claims", "users", ["reviewed_by"], ["id"], "SET NULL"),
    ("fk_reimbursement_claims_paid_by_users", "reimbursement_claims", "users", ["paid_by"], ["id"], "SET NULL"),
    ("fk_statutory_compliance_configs_ca_verified_by_users", "statutory_compliance_configs", "users", ["ca_verified_by"], ["id"], "SET NULL"),
    ("fk_tax_declaration_proofs_verified_by_users", "tax_declaration_proofs", "users", ["verified_by"], ["id"], "SET NULL"),
]

# Columns confirmed nullable=False in ORM where 0 NULLs exist in DB
_SAFE_NOT_NULL_ALIGNMENTS: list[tuple[str, str, sa.types.TypeEngine]] = [
    ("compliance_obligations", "penalty_amount", sa.Numeric(14, 2)),
    ("employee_investment_declarations", "section_80g", sa.Numeric(14, 2)),
    ("employee_investment_declarations", "hra_claimed", sa.Numeric(14, 2)),
    ("employee_investment_declarations", "lta_claimed", sa.Numeric(14, 2)),
    ("employee_investment_declarations", "status", sa.String(30)),
    ("payroll_compliance_challans", "updated_at", sa.DateTime(timezone=True)),
    ("payroll_periods", "is_locked", sa.Boolean()),
    ("shifts", "updated_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    bind = op.get_bind()
    for table, specs in _DRIFTED_COLUMNS.items():
        _add_missing_columns(bind, table, specs)

    _create_missing_indexes(bind, _INDEX_SPECS)
    _create_missing_fks(bind, _FK_SPECS)

    insp = sa.inspect(bind)
    col_cache: dict[str, dict[str, dict]] = {}
    for table, col_name, col_type in _SAFE_NOT_NULL_ALIGNMENTS:
        cols = col_cache.setdefault(table, _cols(insp, table))
        if col_name in cols and cols[col_name]["nullable"]:
            null_cnt = bind.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE {col_name} IS NULL")
            ).scalar_one()
            if null_cnt == 0:
                op.alter_column(
                    table,
                    col_name,
                    existing_type=col_type,
                    nullable=False,
                )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table, col_name, col_type in reversed(_SAFE_NOT_NULL_ALIGNMENTS):
        cols = _cols(insp, table)
        if col_name in cols and not cols[col_name]["nullable"]:
            op.alter_column(
                table,
                col_name,
                existing_type=col_type,
                nullable=True,
            )

    for fk_name, src_tbl, *_ in reversed(_FK_SPECS):
        names, _ = _fks(insp, src_tbl)
        if fk_name in names:
            op.drop_constraint(fk_name, src_tbl, type_="foreignkey")

    for idx_name, table, *_ in reversed(_INDEX_SPECS):
        if idx_name in _idxs(insp, table):
            op.drop_index(idx_name, table_name=table)

    for table, specs in reversed(list(_DRIFTED_COLUMNS.items())):
        existing = _cols(insp, table)
        for col_name, _ in reversed(specs):
            if col_name in existing:
                op.drop_column(table, col_name)
