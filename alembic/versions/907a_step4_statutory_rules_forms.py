"""Step 4 batch 2: state statutory rules, proof workflow and tax forms.

Revision ID: 907a_step4_statutory_forms
Revises: 906a_step3_lock_arrears_ot
"""
from __future__ import annotations

from datetime import date
import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "907a_step4_statutory_forms"
down_revision = "906a_step3_lock_arrears_ot"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _json():
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # Employee-level statutory switches and migrated tax data.
    for name, column in (
        ("pf_membership_active", sa.Column("pf_membership_active", sa.Boolean(), nullable=False, server_default=sa.text("true"))),
        ("pf_higher_wage_opted", sa.Column("pf_higher_wage_opted", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
        ("vpf_rate", sa.Column("vpf_rate", sa.Numeric(7, 6), nullable=False, server_default="0")),
        ("is_pwd", sa.Column("is_pwd", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
        ("state_code", sa.Column("state_code", sa.String(length=2), nullable=True)),
        ("esi_covered_at_period_start", sa.Column("esi_covered_at_period_start", sa.Boolean(), nullable=False, server_default=sa.text("false"))),
    ):
        op.add_column("employees", column)

    for name, column in (
        ("employer_eps_rate", sa.Column("employer_eps_rate", sa.Numeric(7, 6), nullable=False, server_default="0.0833")),
        ("employer_edli_rate", sa.Column("employer_edli_rate", sa.Numeric(7, 6), nullable=False, server_default="0.005")),
        ("pf_admin_rate", sa.Column("pf_admin_rate", sa.Numeric(7, 6), nullable=False, server_default="0.005")),
        ("esi_pwd_wage_ceiling", sa.Column("esi_pwd_wage_ceiling", sa.Numeric(14, 2), nullable=False, server_default="25000.00")),
    ):
        op.add_column("statutory_compliance_configs", column)

    for column in (
        sa.Column("crn_number", sa.String(length=100), nullable=True),
        sa.Column("bank_reference", sa.String(length=150), nullable=True),
        sa.Column("bsr_code", sa.String(length=20), nullable=True),
        sa.Column("challan_serial_number", sa.String(length=50), nullable=True),
    ):
        op.add_column("payroll_compliance_challans", column)

    for column in (
        sa.Column("proof_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("proof_cutoff_date", sa.Date(), nullable=True),
        sa.Column("proof_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_verified_amounts", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("declared_details_json", _json(), nullable=True),
        sa.Column("verified_details_json", _json(), nullable=True),
        sa.Column("previous_employer_income_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("previous_employer_tds_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ytd_tds_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("one_time_bonus_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("variable_pay_paise", sa.BigInteger(), nullable=False, server_default="0"),
    ):
        op.add_column("employee_investment_declarations", column)

    for column in (
        sa.Column("verified_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("verified_by", _uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("document_hash", sa.String(length=64), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
    ):
        op.add_column("tax_declaration_proofs", column)
    op.create_foreign_key("fk_tax_decl_proofs_verified_by_users", "tax_declaration_proofs", "users", ["verified_by"], ["id"], ondelete="SET NULL")

    for column in (
        sa.Column("proof_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("proof_cutoff_date", sa.Date(), nullable=True),
        sa.Column("use_verified_declarations", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("declared_details_json", sa.JSON(), nullable=True),
        sa.Column("verified_details_json", sa.JSON(), nullable=True),
        sa.Column("previous_employer_income_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("previous_employer_tds_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ytd_tds_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("one_time_bonus_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("variable_pay_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("proof_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_by", _uuid(), nullable=True),
    ):
        op.add_column("employee_tax_info", column)
    op.create_foreign_key("fk_employee_tax_info_last_verified_by_users", "employee_tax_info", "users", ["last_verified_by"], ["id"], ondelete="SET NULL")

    op.create_table(
        "state_statutory_rules",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("state_name", sa.String(length=80), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("pt_slabs_json", sa.JSON(), nullable=False),
        sa.Column("lwf_employee_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lwf_employer_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lwf_frequency", sa.String(length=20), nullable=False, server_default="MONTHLY"),
        sa.Column("lwf_applicable_months", sa.JSON(), nullable=False),
        sa.Column("needs_ca_validation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_state_statutory_rules_state_effective", "state_statutory_rules", ["state_code", "effective_from"])
    op.create_index("ix_state_statutory_rules_company_state", "state_statutory_rules", ["company_id", "state_code"])

    op.create_table(
        "financial_year_tax_rules",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("financial_year", sa.String(length=9), nullable=False),
        sa.Column("regime", sa.String(length=10), nullable=False),
        sa.Column("slabs_json", sa.JSON(), nullable=False),
        sa.Column("standard_deduction_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rebate_87a_limit_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("rebate_87a_max_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("chapter_via_limits_json", sa.JSON(), nullable=False),
        sa.Column("surcharge_slabs_json", sa.JSON(), nullable=False),
        sa.Column("cess_rate", sa.Numeric(7, 6), nullable=False, server_default="0.04"),
        sa.Column("proof_cutoff_date", sa.Date(), nullable=True),
        sa.Column("needs_ca_validation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "financial_year", "regime", name="uq_fy_tax_rule_company_year_regime"),
    )
    op.create_index("ix_fy_tax_rules_year_regime", "financial_year_tax_rules", ["financial_year", "regime"])

    op.create_table(
        "statutory_forms",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("company_id", _uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("employee_id", _uuid(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True),
        sa.Column("period_id", _uuid(), sa.ForeignKey("payroll_periods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("form_type", sa.String(length=20), nullable=False),
        sa.Column("financial_year", sa.String(length=9), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("validation_errors_json", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("file_url", sa.String(length=500), nullable=True),
        sa.Column("generated_by", _uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_statutory_forms_company_type_period", "statutory_forms", ["company_id", "form_type", "period_id"])
    op.create_index("ix_statutory_forms_employee_year", "statutory_forms", ["employee_id", "financial_year"])

    # Defaults are deterministic and idempotent.  They are intentionally marked
    # for CA review rather than presented as legal sign-off.
    state_rows = [
        ("MH", "Maharashtra", 1200, 3600, "SEMI_ANNUAL", [6, 12], [{"min_gross_paise": 0, "max_gross_paise": 750000, "amount_paise": 0, "gender": "MALE"}, {"min_gross_paise": 750001, "max_gross_paise": 1000000, "amount_paise": 17500, "gender": "MALE"}, {"min_gross_paise": 0, "max_gross_paise": 1000000, "amount_paise": 0, "gender": "FEMALE"}, {"min_gross_paise": 1000001, "max_gross_paise": None, "amount_paise": 20000, "monthly_amounts": {"2": 30000}}]),
        ("KA", "Karnataka", 2000, 4000, "ANNUAL", [12], [{"min_gross_paise": 0, "max_gross_paise": 1499999, "amount_paise": 0}, {"min_gross_paise": 1500000, "max_gross_paise": None, "amount_paise": 20000}]),
        ("TN", "Tamil Nadu", 0, 0, "ANNUAL", [12], [{'min_gross_paise': 0, 'max_gross_paise': 2100000, 'amount_paise': 0}, {'min_gross_paise': 2100001, 'max_gross_paise': 3000000, 'amount_paise': 10000}, {'min_gross_paise': 3000001, 'max_gross_paise': 4500000, 'amount_paise': 23500}, {'min_gross_paise': 4500001, 'max_gross_paise': 6000000, 'amount_paise': 51000}, {'min_gross_paise': 6000001, 'max_gross_paise': 7500000, 'amount_paise': 76000}, {'min_gross_paise': 7500001, 'max_gross_paise': None, 'amount_paise': 102500}]),
        ("TS", "Telangana", 0, 0, "ANNUAL", [12], [{'min_gross_paise': 0, 'max_gross_paise': 1500000, 'amount_paise': 0}, {'min_gross_paise': 1500001, 'max_gross_paise': 2000000, 'amount_paise': 15000}, {'min_gross_paise': 2000001, 'max_gross_paise': None, 'amount_paise': 20000}]),
        ("DL", "Delhi", 100, 300, "SEMI_ANNUAL", [6, 12], []),
        ("HR", "Haryana", 2500, 5000, "MONTHLY", list(range(1, 13)), []),
        ("UP", "Uttar Pradesh", 0, 0, "MONTHLY", [], []),
        ("WB", "West Bengal", 0, 0, "SEMI_ANNUAL", [6, 12], [{'min_gross_paise': 0, 'max_gross_paise': 1000000, 'amount_paise': 0}, {'min_gross_paise': 1000001, 'max_gross_paise': 1500000, 'amount_paise': 11000}, {'min_gross_paise': 1500001, 'max_gross_paise': 2500000, 'amount_paise': 13000}, {'min_gross_paise': 2500001, 'max_gross_paise': 4000000, 'amount_paise': 15000}, {'min_gross_paise': 4000001, 'max_gross_paise': None, 'amount_paise': 20000}]),
        ("GJ", "Gujarat", 600, 1200, "SEMI_ANNUAL", [6, 12], [{"min_gross_paise": 0, "max_gross_paise": 1200000, "amount_paise": 0}, {"min_gross_paise": 1200001, "max_gross_paise": None, "amount_paise": 20000}]),
        ("RJ", "Rajasthan", 0, 0, "MONTHLY", [], []),
        ("MP", "Madhya Pradesh", 0, 0, "SEMI_ANNUAL", [6, 12], [{'min_gross_paise': 0, 'max_gross_paise': 1875000, 'amount_paise': 0}, {'min_gross_paise': 1875001, 'max_gross_paise': 2500000, 'amount_paise': 12500}, {'min_gross_paise': 2500001, 'max_gross_paise': 3333300, 'amount_paise': 16700}, {'min_gross_paise': 3333301, 'max_gross_paise': None, 'amount_paise': 20800, 'monthly_amounts': {'3': 21200}}]),
    ]
    for code, name, employee, employer, frequency, months, slabs in state_rows:
        rule_id = uuid.uuid5(uuid.NAMESPACE_URL, f"apiofc360:state-rule:{code}:2020-01-01")
        slabs_sql = json.dumps(slabs).replace("'", "''")
        months_sql = json.dumps(months).replace("'", "''")
        op.execute(
            f"""
            INSERT INTO state_statutory_rules
                (id, company_id, state_code, state_name, effective_from, effective_to,
                 pt_slabs_json, lwf_employee_paise, lwf_employer_paise, lwf_frequency,
                 lwf_applicable_months, needs_ca_validation, is_active)
            VALUES
                ('{rule_id}', NULL, '{code}', '{name}', '2020-01-01', NULL,
                 '{slabs_sql}'::json, {employee}, {employer}, '{frequency}',
                 '{months_sql}'::json, true, true)
            ON CONFLICT (id) DO NOTHING
            """
        )



def downgrade() -> None:
    op.drop_index("ix_statutory_forms_employee_year", table_name="statutory_forms")
    op.drop_index("ix_statutory_forms_company_type_period", table_name="statutory_forms")
    op.drop_table("statutory_forms")
    op.drop_index("ix_fy_tax_rules_year_regime", table_name="financial_year_tax_rules")
    op.drop_table("financial_year_tax_rules")
    op.drop_index("ix_state_statutory_rules_company_state", table_name="state_statutory_rules")
    op.drop_index("ix_state_statutory_rules_state_effective", table_name="state_statutory_rules")
    op.drop_table("state_statutory_rules")
    op.drop_constraint("fk_employee_tax_info_last_verified_by_users", "employee_tax_info", type_="foreignkey")
    for name in ("last_verified_by", "last_verified_at", "proof_submitted_at", "variable_pay_paise", "one_time_bonus_paise", "ytd_tds_paise", "previous_employer_tds_paise", "previous_employer_income_paise", "verified_details_json", "declared_details_json", "use_verified_declarations", "proof_cutoff_date", "proof_status"):
        op.drop_column("employee_tax_info", name)
    op.drop_constraint("fk_tax_decl_proofs_verified_by_users", "tax_declaration_proofs", type_="foreignkey")
    for name in ("file_path", "document_hash", "rejection_reason", "verified_at", "verified_by", "status", "verified_amount"):
        op.drop_column("tax_declaration_proofs", name)
    for name in ("variable_pay_paise", "one_time_bonus_paise", "ytd_tds_paise", "previous_employer_tds_paise", "previous_employer_income_paise", "verified_details_json", "declared_details_json", "use_verified_amounts", "proof_submitted_at", "proof_cutoff_date", "proof_status"):
        op.drop_column("employee_investment_declarations", name)
    for name in ("challan_serial_number", "bsr_code", "bank_reference", "crn_number"):
        op.drop_column("payroll_compliance_challans", name)
    for name in ("esi_pwd_wage_ceiling", "pf_admin_rate", "employer_edli_rate", "employer_eps_rate"):
        op.drop_column("statutory_compliance_configs", name)
    for name in ("esi_covered_at_period_start", "state_code", "is_pwd", "vpf_rate", "pf_higher_wage_opted", "pf_membership_active"):
        op.drop_column("employees", name)
