"""Batch 5: mobile, WhatsApp, grievance/POSH, policy, compliance and entities.

Revision ID: 909a_batch5_employee_experience
Revises: 908a_batch4_onboarding_fnf
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "909a_batch5_employee_experience"
down_revision = "908a_batch4_onboarding_fnf"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _tenant_timestamps():
    return [sa.Column("company_id", _uuid(), nullable=True), *_timestamps()]


def _fk(table, column, target, ondelete=None, name=None):
    kwargs = {"ondelete": ondelete} if ondelete else {}
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=name or op.f(f"fk_{table}_{column}_{target}"), **kwargs,
    )


def upgrade() -> None:
    # Multi-entity payroll periods/runs. NULLS NOT DISTINCT preserves legacy
    # entity-less uniqueness while allowing one period/run per entity.
    op.add_column("payroll_periods", sa.Column("legal_entity_id", _uuid(), nullable=True))
    op.create_foreign_key("fk_payroll_periods_legal_entity_id_legal_entities", "payroll_periods", "legal_entities", ["legal_entity_id"], ["id"], ondelete="RESTRICT")
    op.execute(sa.text('ALTER TABLE payroll_periods DROP CONSTRAINT IF EXISTS "uq_period_company_month_year"'))
    op.create_unique_constraint("uq_period_company_month_year", "payroll_periods", ["company_id", "legal_entity_id", "period_month", "period_year"], postgresql_nulls_not_distinct=True)
    op.add_column("payroll_runs", sa.Column("legal_entity_id", _uuid(), nullable=True))
    op.create_foreign_key("fk_payroll_runs_legal_entity_id_legal_entities", "payroll_runs", "legal_entities", ["legal_entity_id"], ["id"], ondelete="RESTRICT")
    op.execute(sa.text('ALTER TABLE payroll_runs DROP CONSTRAINT IF EXISTS "uq_payroll_run_company_period"'))
    op.create_unique_constraint("uq_payroll_run_company_period", "payroll_runs", ["company_id", "legal_entity_id", "period_month", "period_year"], postgresql_nulls_not_distinct=True)

    op.create_table(
        "entity_payroll_calendars", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("legal_entity_id", _uuid(), nullable=False), sa.Column("payroll_period_id", _uuid(), nullable=True),
        sa.Column("period_month", sa.Integer(), nullable=False), sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("processing_date", sa.Date(), nullable=False), sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("attendance_cutoff_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'OPEN'"), nullable=False),
        _fk("entity_payroll_calendars", "company_id", "companies", "CASCADE"),
        _fk("entity_payroll_calendars", "legal_entity_id", "legal_entities", "CASCADE"),
        _fk("entity_payroll_calendars", "payroll_period_id", "payroll_periods", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_payroll_calendars")),
        sa.UniqueConstraint("legal_entity_id", "period_month", "period_year", name="uq_entity_payroll_calendar_period"),
    )
    op.create_table(
        "employee_entity_transfers", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("employee_id", _uuid(), nullable=False), sa.Column("from_legal_entity_id", _uuid(), nullable=True),
        sa.Column("to_legal_entity_id", _uuid(), nullable=False), sa.Column("from_branch_id", _uuid(), nullable=True),
        sa.Column("to_branch_id", _uuid(), nullable=True), sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'SCHEDULED'"), nullable=False),
        sa.Column("requested_by", _uuid(), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _fk("employee_entity_transfers", "company_id", "companies", "CASCADE"),
        _fk("employee_entity_transfers", "employee_id", "employees", "CASCADE"),
        _fk("employee_entity_transfers", "from_legal_entity_id", "legal_entities", "SET NULL", "fk_entity_transfer_from_legal_entity"),
        _fk("employee_entity_transfers", "to_legal_entity_id", "legal_entities", "RESTRICT"),
        _fk("employee_entity_transfers", "from_branch_id", "branches", "SET NULL"),
        _fk("employee_entity_transfers", "to_branch_id", "branches", "SET NULL"),
        _fk("employee_entity_transfers", "requested_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employee_entity_transfers")),
    )

    # Versioned, targeted policies and assignment-level acknowledgement evidence.
    for column in (
        sa.Column("version_number", sa.String(length=20), server_default=sa.text("'1.0'"), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True), sa.Column("supersedes_policy_id", _uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'DRAFT'"), nullable=False),
        sa.Column("acknowledgement_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("acknowledgement_due_date", sa.Date(), nullable=True),
        sa.Column("reminder_after_days", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("escalation_after_days", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.Column("target_branch_ids", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("target_departments", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("target_roles", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("target_employment_types", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ):
        op.add_column("company_policy_documents", column)
    op.create_foreign_key("fk_policy_document_supersedes", "company_policy_documents", "company_policy_documents", ["supersedes_policy_id"], ["id"], ondelete="SET NULL")
    for column in (
        sa.Column("policy_document_id", _uuid(), nullable=True), sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("signature_hash", sa.String(length=64), nullable=True), sa.Column("request_id", sa.String(length=100), nullable=True),
    ):
        op.add_column("employee_policy_acceptances", column)
    op.create_foreign_key("fk_policy_acceptance_document", "employee_policy_acceptances", "company_policy_documents", ["policy_document_id"], ["id"], ondelete="CASCADE")
    op.create_table(
        "policy_acknowledgement_assignments", sa.Column("id", _uuid(), nullable=False),
        sa.Column("policy_document_id", _uuid(), nullable=False), sa.Column("employee_id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True), sa.Column("acceptance_id", _uuid(), nullable=True),
        *_timestamps(),
        _fk("policy_acknowledgement_assignments", "policy_document_id", "company_policy_documents", "CASCADE", "fk_policy_assignment_document"),
        _fk("policy_acknowledgement_assignments", "employee_id", "employees", "CASCADE"),
        _fk("policy_acknowledgement_assignments", "company_id", "companies", "CASCADE"),
        _fk("policy_acknowledgement_assignments", "acceptance_id", "employee_policy_acceptances", "SET NULL", "fk_policy_assignment_acceptance"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_acknowledgement_assignments")),
        sa.UniqueConstraint("policy_document_id", "employee_id", name="uq_policy_assignment_employee"),
    )
    op.create_index("ix_policy_assignment_pending", "policy_acknowledgement_assignments", ["company_id", "status", "due_at"])

    # Bank reverse feeds and re-payout lineage.
    op.add_column("payment_batches", sa.Column("retry_of_batch_id", _uuid(), nullable=True))
    op.create_foreign_key("fk_payment_batches_retry_of_batch_id_payment_batches", "payment_batches", "payment_batches", ["retry_of_batch_id"], ["id"], ondelete="SET NULL")
    op.add_column("payment_batch_items", sa.Column("utr_number", sa.String(length=100), nullable=True))
    op.add_column("payment_batch_items", sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_batch_items", sa.Column("repayout_batch_id", _uuid(), nullable=True))
    op.create_foreign_key("fk_payment_batch_items_repayout_batch_id_payment_batches", "payment_batch_items", "payment_batches", ["repayout_batch_id"], ["id"], ondelete="SET NULL")
    for column in (
        sa.Column("filing_frequency", sa.String(length=20), server_default=sa.text("'MONTHLY'"), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filing_reference", sa.String(length=150), nullable=True),
        sa.Column("remarks", sa.String(length=500), nullable=True),
    ):
        op.add_column("payroll_compliance_due_dates", column)

    # Confidential grievance cases and restricted event timeline.
    op.create_table(
        "grievance_cases", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("case_number", sa.String(length=40), nullable=False), sa.Column("reporter_employee_id", _uuid(), nullable=True),
        sa.Column("reporter_user_id", _uuid(), nullable=True), sa.Column("is_anonymous", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_confidential", sa.Boolean(), server_default=sa.text("true"), nullable=False), sa.Column("receipt_token_hash", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False), sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("accused_user_ids", sa.JSON(), nullable=False),
        sa.Column("priority", sa.String(length=20), server_default=sa.text("'NORMAL'"), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_level", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("investigator_id", _uuid(), nullable=True), sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True), sa.Column("resolved_by", _uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True), sa.Column("appeal_reason", sa.Text(), nullable=True),
        sa.Column("appealed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("appeal_status", sa.String(length=30), nullable=True),
        sa.Column("appeal_resolution", sa.Text(), nullable=True), sa.Column("appeal_resolved_at", sa.DateTime(timezone=True), nullable=True),
        _fk("grievance_cases", "company_id", "companies", "CASCADE"),
        _fk("grievance_cases", "reporter_employee_id", "employees", "SET NULL"), _fk("grievance_cases", "reporter_user_id", "users", "SET NULL"),
        _fk("grievance_cases", "investigator_id", "users", "SET NULL"), _fk("grievance_cases", "resolved_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grievance_cases")),
        sa.UniqueConstraint("company_id", "case_number", name="uq_grievance_company_number"),
        sa.UniqueConstraint("receipt_token_hash", name=op.f("uq_grievance_cases_receipt_token_hash")),
    )
    op.create_index("ix_grievance_cases_company_status", "grievance_cases", ["company_id", "status"])
    op.create_index("ix_grievance_cases_sla", "grievance_cases", ["sla_due_at", "status"])
    op.create_table(
        "grievance_case_events", sa.Column("id", _uuid(), nullable=False), sa.Column("case_id", _uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False), sa.Column("actor_id", _uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True), sa.Column("event_metadata", sa.JSON(), nullable=False), *_timestamps(),
        _fk("grievance_case_events", "case_id", "grievance_cases", "CASCADE"), _fk("grievance_case_events", "actor_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grievance_case_events")),
    )
    op.create_index("ix_grievance_events_case", "grievance_case_events", ["case_id", "created_at"])

    # POSH ICC, inquiry, encrypted evidence, training and annual returns.
    op.create_table(
        "posh_icc_committees", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("name", sa.String(length=150), nullable=False), sa.Column("term_start", sa.Date(), nullable=False),
        sa.Column("term_end", sa.Date(), nullable=False), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        _fk("posh_icc_committees", "company_id", "companies", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posh_icc_committees")),
        sa.UniqueConstraint("company_id", "name", name="uq_posh_icc_company_name"),
    )
    op.create_table(
        "posh_icc_members", sa.Column("id", _uuid(), nullable=False), sa.Column("committee_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=True), sa.Column("employee_id", _uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False), sa.Column("gender", sa.String(length=20), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False), sa.Column("is_external", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False), sa.Column("appointed_at", sa.Date(), nullable=False), *_timestamps(),
        _fk("posh_icc_members", "committee_id", "posh_icc_committees", "CASCADE"), _fk("posh_icc_members", "user_id", "users", "SET NULL"),
        _fk("posh_icc_members", "employee_id", "employees", "SET NULL"), sa.PrimaryKeyConstraint("id", name=op.f("pk_posh_icc_members")),
    )
    op.create_index("ix_posh_icc_members_committee", "posh_icc_members", ["committee_id", "is_active"])
    op.create_table(
        "posh_complaints", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("complaint_number", sa.String(length=40), nullable=False), sa.Column("committee_id", _uuid(), nullable=False),
        sa.Column("reporter_employee_id", _uuid(), nullable=True), sa.Column("reporter_user_id", _uuid(), nullable=True),
        sa.Column("is_anonymous", sa.Boolean(), server_default=sa.text("false"), nullable=False), sa.Column("receipt_token_hash", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("accused_user_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'FILED'"), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("inquiry_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conciliation_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("conciliation_status", sa.String(length=30), nullable=True), sa.Column("conciliation_terms", sa.Text(), nullable=True),
        sa.Column("conciliated_at", sa.DateTime(timezone=True), nullable=True), sa.Column("inquiry_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inquiry_completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("final_recommendation", sa.Text(), nullable=True),
        sa.Column("recommendation_at", sa.DateTime(timezone=True), nullable=True), sa.Column("recommendation_by", _uuid(), nullable=True),
        _fk("posh_complaints", "company_id", "companies", "CASCADE"), _fk("posh_complaints", "committee_id", "posh_icc_committees", "RESTRICT"),
        _fk("posh_complaints", "reporter_employee_id", "employees", "SET NULL"), _fk("posh_complaints", "reporter_user_id", "users", "SET NULL"),
        _fk("posh_complaints", "recommendation_by", "users", "SET NULL"), sa.PrimaryKeyConstraint("id", name=op.f("pk_posh_complaints")),
        sa.UniqueConstraint("company_id", "complaint_number", name="uq_posh_company_complaint_number"),
        sa.UniqueConstraint("receipt_token_hash", name=op.f("uq_posh_complaints_receipt_token_hash")),
    )
    op.create_index("ix_posh_complaints_inquiry_due", "posh_complaints", ["inquiry_due_at", "status"])
    op.create_table(
        "posh_evidence_vault", sa.Column("id", _uuid(), nullable=False), sa.Column("complaint_id", _uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False), sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False), sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("key_version", sa.String(length=30), server_default=sa.text("'v1'"), nullable=False), sa.Column("uploaded_by", _uuid(), nullable=True), *_timestamps(),
        _fk("posh_evidence_vault", "complaint_id", "posh_complaints", "CASCADE"), _fk("posh_evidence_vault", "uploaded_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posh_evidence_vault")),
    )
    op.create_index("ix_posh_evidence_complaint", "posh_evidence_vault", ["complaint_id", "created_at"])
    op.create_table(
        "posh_training_records", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("employee_id", _uuid(), nullable=True), sa.Column("icc_member_id", _uuid(), nullable=True),
        sa.Column("audience", sa.String(length=20), nullable=False), sa.Column("training_title", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=150), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True), sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("certificate_reference", sa.String(length=100), nullable=True),
        _fk("posh_training_records", "company_id", "companies", "CASCADE"), _fk("posh_training_records", "employee_id", "employees", "CASCADE"),
        _fk("posh_training_records", "icc_member_id", "posh_icc_members", "CASCADE"), sa.PrimaryKeyConstraint("id", name=op.f("pk_posh_training_records")),
    )
    op.create_index("ix_posh_training_company_employee", "posh_training_records", ["company_id", "employee_id"])
    op.create_table(
        "posh_annual_returns", sa.Column("id", _uuid(), nullable=False), *_tenant_timestamps(),
        sa.Column("return_year", sa.Integer(), nullable=False), sa.Column("section_21", sa.JSON(), nullable=False),
        sa.Column("section_22", sa.JSON(), nullable=False), sa.Column("generated_by", _uuid(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        _fk("posh_annual_returns", "company_id", "companies", "CASCADE"), _fk("posh_annual_returns", "generated_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posh_annual_returns")),
        sa.UniqueConstraint("company_id", "return_year", name="uq_posh_annual_return_year"),
    )

    # Mobile push/offline ledger and WhatsApp provider dedupe/conversation state.
    op.create_table(
        "mobile_push_subscriptions", sa.Column("id", _uuid(), nullable=False), sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("user_id", _uuid(), nullable=False), sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("endpoint_or_token", sa.Text(), nullable=False), sa.Column("subscription_hash", sa.String(length=64), nullable=False),
        sa.Column("keys_json", sa.JSON(), nullable=True), sa.Column("device_id", sa.String(length=150), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True), sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False), *_timestamps(),
        _fk("mobile_push_subscriptions", "company_id", "companies", "CASCADE"), _fk("mobile_push_subscriptions", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mobile_push_subscriptions")),
        sa.UniqueConstraint("subscription_hash", name="uq_mobile_push_subscription_hash"),
    )
    op.create_index("ix_mobile_push_user", "mobile_push_subscriptions", ["user_id", "company_id", "is_active"])
    op.create_table(
        "mobile_idempotency_records", sa.Column("id", _uuid(), nullable=False), sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("user_id", _uuid(), nullable=False), sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False), sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'PROCESSING'"), nullable=False),
        sa.Column("resource_id", _uuid(), nullable=True), sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True), *_timestamps(),
        _fk("mobile_idempotency_records", "company_id", "companies", "CASCADE"), _fk("mobile_idempotency_records", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mobile_idempotency_records")),
        sa.UniqueConstraint("user_id", "operation", "idempotency_key", name="uq_mobile_idempotency_user_operation_key"),
    )
    op.create_index("ix_mobile_idempotency_company", "mobile_idempotency_records", ["company_id", "created_at"])
    op.create_table(
        "whatsapp_inbound_messages", sa.Column("id", _uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=150), nullable=False), sa.Column("from_phone", sa.String(length=20), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False), sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_inbound_messages")),
        sa.UniqueConstraint("provider_message_id", name=op.f("uq_whatsapp_inbound_messages_provider_message_id")),
    )
    op.create_index("ix_whatsapp_inbound_phone", "whatsapp_inbound_messages", ["from_phone", "received_at"])
    op.create_table(
        "whatsapp_conversations", sa.Column("user_id", _uuid(), nullable=False), sa.Column("flow", sa.String(length=30), nullable=False),
        sa.Column("step", sa.String(length=30), nullable=False), sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), *_timestamps(),
        _fk("whatsapp_conversations", "user_id", "users", "CASCADE"), sa.PrimaryKeyConstraint("user_id", name=op.f("pk_whatsapp_conversations")),
    )


def downgrade() -> None:
    for table in (
        "whatsapp_conversations", "whatsapp_inbound_messages", "mobile_idempotency_records", "mobile_push_subscriptions",
        "posh_annual_returns", "posh_training_records", "posh_evidence_vault", "posh_complaints", "posh_icc_members",
        "posh_icc_committees", "grievance_case_events", "grievance_cases", "policy_acknowledgement_assignments",
        "employee_entity_transfers", "entity_payroll_calendars",
    ):
        op.drop_table(table)
    for name in ("remarks", "filing_reference", "filed_at", "filing_frequency"):
        op.drop_column("payroll_compliance_due_dates", name)
    op.drop_constraint("fk_payment_batch_items_repayout_batch_id_payment_batches", "payment_batch_items", type_="foreignkey")
    for name in ("repayout_batch_id", "reconciled_at", "utr_number"):
        op.drop_column("payment_batch_items", name)
    op.drop_constraint("fk_payment_batches_retry_of_batch_id_payment_batches", "payment_batches", type_="foreignkey")
    op.drop_column("payment_batches", "retry_of_batch_id")
    op.drop_constraint("fk_policy_acceptance_document", "employee_policy_acceptances", type_="foreignkey")
    for name in ("request_id", "signature_hash", "user_agent", "policy_document_id"):
        op.drop_column("employee_policy_acceptances", name)
    op.drop_constraint("fk_policy_document_supersedes", "company_policy_documents", type_="foreignkey")
    for name in ("updated_at", "target_employment_types", "target_roles", "target_departments", "target_branch_ids", "escalation_after_days", "reminder_after_days", "acknowledgement_due_date", "acknowledgement_required", "status", "supersedes_policy_id", "effective_date", "version_number"):
        op.drop_column("company_policy_documents", name)
    op.drop_constraint("uq_payroll_run_company_period", "payroll_runs", type_="unique")
    op.create_unique_constraint("uq_payroll_run_company_period", "payroll_runs", ["company_id", "period_month", "period_year"])
    op.drop_constraint("fk_payroll_runs_legal_entity_id_legal_entities", "payroll_runs", type_="foreignkey")
    op.drop_column("payroll_runs", "legal_entity_id")
    op.drop_constraint("uq_period_company_month_year", "payroll_periods", type_="unique")
    op.create_unique_constraint("uq_period_company_month_year", "payroll_periods", ["company_id", "period_month", "period_year"])
    op.drop_constraint("fk_payroll_periods_legal_entity_id_legal_entities", "payroll_periods", type_="foreignkey")
    op.drop_column("payroll_periods", "legal_entity_id")
