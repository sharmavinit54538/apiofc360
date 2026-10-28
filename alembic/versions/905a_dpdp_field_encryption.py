"""Add DPDP ledgers and encrypted employee PII storage.

Revision ID: 905a_dpdp_field_encryption
Revises: 904a_complete_model_registry
Create Date: 2026-10-27

The migration is non-destructive: existing plaintext remains readable by the
ORM until ``scripts/backfill_encrypted_pii.py`` is run.  Cipher columns are
widened to Text, blind-index columns are added, and no personal-data columns or
statutory records are dropped.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "905a_dpdp_field_encryption"
down_revision: Union[str, None] = "904a_complete_model_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EMPLOYEE_PII_TYPES = {
    "aadhaar_number": sa.String(length=20),
    "pan_number": sa.String(length=10),
    "uan_number": sa.String(length=12),
    "passport_number": sa.String(length=20),
    "voter_id": sa.String(length=20),
}


def upgrade() -> None:
    for column_name, existing_type in _EMPLOYEE_PII_TYPES.items():
        op.alter_column("employees", column_name, existing_type=existing_type, type_=sa.Text(), existing_nullable=True)
        op.add_column("employees", sa.Column(f"{column_name}_blind_idx", sa.String(length=64), nullable=True))

    op.alter_column(
        "employee_bank_accounts",
        "account_number",
        existing_type=sa.String(length=30),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "employee_bank_accounts",
        "ifsc_code",
        existing_type=sa.String(length=15),
        type_=sa.Text(),
        existing_nullable=False,
    )

    for index_name, column_name in (
        ("ix_employees_company_aadhaar_blind_idx", "aadhaar_number_blind_idx"),
        ("ix_employees_company_pan_blind_idx", "pan_number_blind_idx"),
        ("ix_employees_company_uan_blind_idx", "uan_number_blind_idx"),
        ("ix_employees_company_passport_blind_idx", "passport_number_blind_idx"),
        ("ix_employees_company_voter_blind_idx", "voter_id_blind_idx"),
    ):
        op.create_index(index_name, "employees", ["company_id", column_name], unique=False)

    op.create_table(
        "data_consent_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("purpose_code", sa.String(length=50), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("consent_status", sa.String(length=20), server_default=sa.text("'GRANTED'"), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "consent_status IN ('GRANTED', 'WITHDRAWN')",
            name=op.f("ck_data_consent_ledger_consent_status_allowed"),
        ),
        sa.CheckConstraint(
            "purpose_code IN ('PAYROLL_PROCESSING', 'BGV_VERIFICATION', 'BIOMETRIC_ATTENDANCE', 'TAX_FILING')",
            name=op.f("ck_data_consent_ledger_purpose_code_allowed"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_data_consent_ledger_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name=op.f("fk_data_consent_ledger_employee_id_employees"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_data_consent_ledger_user_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_consent_ledger")),
    )
    op.create_index("ix_data_consent_ledger_company_employee", "data_consent_ledger", ["company_id", "employee_id"], unique=False)
    op.create_index("ix_data_consent_ledger_company_status", "data_consent_ledger", ["company_id", "consent_status"], unique=False)
    op.create_index("ix_data_consent_ledger_employee_purpose", "data_consent_ledger", ["employee_id", "purpose_code"], unique=False)

    op.create_table(
        "data_retention_policies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("retention_days", sa.Integer(), server_default=sa.text("2920"), nullable=False),
        sa.Column("auto_anonymise_after_exit", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("retention_days >= 0", name=op.f("ck_data_retention_policies_retention_days_nonnegative")),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_data_retention_policies_company_id_companies"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_retention_policies")),
        sa.UniqueConstraint("company_id", "entity_type", name="uq_data_retention_policy_company_entity"),
    )
    op.create_index("ix_data_retention_policies_company_id", "data_retention_policies", ["company_id"], unique=False)

    op.create_table(
        "data_subject_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("request_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("execution_summary", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "request_type IN ('EXPORT', 'ERASURE', 'CORRECTION')",
            name=op.f("ck_data_subject_requests_request_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'EXECUTED', 'REJECTED_STATUTORY_HOLD')",
            name=op.f("ck_data_subject_requests_request_status_allowed"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_data_subject_requests_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name=op.f("fk_data_subject_requests_employee_id_employees"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], name=op.f("fk_data_subject_requests_reviewed_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_subject_requests")),
    )
    op.create_index("ix_data_subject_requests_company_employee", "data_subject_requests", ["company_id", "employee_id"], unique=False)
    op.create_index("ix_data_subject_requests_company_status", "data_subject_requests", ["company_id", "status"], unique=False)

    # Defence in depth for the ORM immutability guard in models/audit_log.py:
    # even direct SQL cannot alter or delete a PII disclosure event.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_pii_unmask_audit_tampering()
        RETURNS trigger AS $$
        BEGIN
            IF OLD.action = 'PII_UNMASK_ACCESS' THEN
                RAISE EXCEPTION 'PII_UNMASK_ACCESS audit events are immutable';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_pii_unmask_audit_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_pii_unmask_audit_tampering()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_pii_unmask_audit_immutable ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_pii_unmask_audit_tampering()")
    op.drop_index("ix_data_subject_requests_company_status", table_name="data_subject_requests")
    op.drop_index("ix_data_subject_requests_company_employee", table_name="data_subject_requests")
    op.drop_table("data_subject_requests")
    op.drop_index("ix_data_retention_policies_company_id", table_name="data_retention_policies")
    op.drop_table("data_retention_policies")
    op.drop_index("ix_data_consent_ledger_employee_purpose", table_name="data_consent_ledger")
    op.drop_index("ix_data_consent_ledger_company_status", table_name="data_consent_ledger")
    op.drop_index("ix_data_consent_ledger_company_employee", table_name="data_consent_ledger")
    op.drop_table("data_consent_ledger")

    for index_name, _ in (
        ("ix_employees_company_aadhaar_blind_idx", "aadhaar_number_blind_idx"),
        ("ix_employees_company_pan_blind_idx", "pan_number_blind_idx"),
        ("ix_employees_company_uan_blind_idx", "uan_number_blind_idx"),
        ("ix_employees_company_passport_blind_idx", "passport_number_blind_idx"),
        ("ix_employees_company_voter_blind_idx", "voter_id_blind_idx"),
    ):
        op.drop_index(index_name, table_name="employees")

    for column_name, original_type in _EMPLOYEE_PII_TYPES.items():
        op.drop_column("employees", f"{column_name}_blind_idx")
        op.alter_column("employees", column_name, existing_type=sa.Text(), type_=original_type, existing_nullable=True)

    op.alter_column(
        "employee_bank_accounts", "ifsc_code", existing_type=sa.Text(), type_=sa.String(length=15), existing_nullable=False
    )
    op.alter_column(
        "employee_bank_accounts", "account_number", existing_type=sa.Text(), type_=sa.String(length=30), existing_nullable=False
    )
