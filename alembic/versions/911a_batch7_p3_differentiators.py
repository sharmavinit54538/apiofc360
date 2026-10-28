"""Batch 7: P3 differentiators, features 34 through 44.

Revision ID: 911a_batch7_p3_differentiators
Revises: 910a_batch6_growth_enterprise
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "911a_batch7_p3_differentiators"
down_revision = "910a_batch6_growth_enterprise"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _fk(table, column, target, ondelete=None):
    kwargs = {"ondelete": ondelete} if ondelete else {}
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"), **kwargs,
    )


def _add_columns(table, columns):
    for column in columns:
        op.add_column(table, column)


def _drop_columns(table, names):
    for name in reversed(names):
        op.drop_column(table, name)


def upgrade() -> None:
    _add_columns("companies", [
        sa.Column("custom_domain", sa.String(length=255), nullable=True),
        sa.Column("whitelabel_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("brand_display_name", sa.String(length=150), nullable=True),
        sa.Column("brand_primary_color", sa.String(length=7), nullable=False, server_default=sa.text("'#17365D'")),
        sa.Column("brand_secondary_color", sa.String(length=7), nullable=False, server_default=sa.text("'#EAF2F8'")),
        sa.Column("brand_logo_url", sa.String(length=500), nullable=True),
        sa.Column("brand_favicon_url", sa.String(length=500), nullable=True),
        sa.Column("email_sender_name", sa.String(length=150), nullable=True),
        sa.Column("email_sender_address", sa.String(length=255), nullable=True),
        sa.Column("email_reply_to", sa.String(length=255), nullable=True),
        sa.Column("branded_pdf_header_text", sa.String(length=300), nullable=True),
    ])
    op.create_unique_constraint("uq_companies_custom_domain", "companies", ["custom_domain"])

    op.add_column("employees", sa.Column("last_promotion_date", sa.Date(), nullable=True))
    _add_columns("applications", [
        sa.Column("voluntary_demographics", sa.JSON(), nullable=True),
        sa.Column("diversity_consent_at", sa.DateTime(timezone=True), nullable=True),
    ])
    _add_columns("employee_risk_assessments", [
        sa.Column("flight_risk_score", sa.Integer(), nullable=True),
        sa.Column("risk_factors_json", sa.JSON(), nullable=True),
        sa.Column("retention_playbook_json", sa.JSON(), nullable=True),
        sa.Column("compa_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("tenure_months", sa.Integer(), nullable=True),
        sa.Column("months_since_promotion", sa.Integer(), nullable=True),
        sa.Column("manager_attrition_pct", sa.Numeric(7, 2), nullable=True),
        sa.Column("model_version", sa.String(length=50), nullable=True),
    ])

    for table in ("salary_structures", "compensations"):
        _add_columns(table, [
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")),
            sa.Column("fx_rate_to_inr", sa.Numeric(20, 8), nullable=False, server_default=sa.text("1")),
        ])

    _add_columns("payroll_runs", [
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")),
        sa.Column("base_currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default=sa.text("'IN'")),
        sa.Column("fx_rate_to_base", sa.Numeric(20, 8), nullable=False, server_default=sa.text("1")),
        sa.Column("fx_rate_snapshot", sa.JSON(), nullable=True),
        sa.Column("fx_rate_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("statutory_rules_snapshot", sa.JSON(), nullable=True),
        sa.Column("statutory_rule_version", sa.String(length=100), nullable=False, server_default=sa.text("'IN_LEGACY_STATUTORY_SERVICE'")),
        sa.Column("total_gross_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_deductions_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_net_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    ])
    _add_columns("payroll_run_employees", [
        sa.Column("gross_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_deductions_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("net_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    ])
    _add_columns("payslips", [
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")),
        sa.Column("gross_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_deductions_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("net_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    ])

    # Existing rows are INR/IN by definition.  Backfill their base-denominated
    # values and immutable 1.0 FX metadata instead of leaving legacy ambiguity.
    op.execute("""
        UPDATE payroll_runs
        SET total_gross_base_paise = total_gross_paise,
            total_deductions_base_paise = total_deductions_paise,
            total_net_base_paise = total_net_paise,
            fx_rate_locked_at = COALESCE(updated_at, created_at, now()),
            fx_rate_snapshot = jsonb_build_object(
                'currency', 'INR', 'base_currency', 'INR', 'rate_to_base', '1.00000000',
                'source', 'LEGACY_INR_BACKFILL', 'rate_as_of', COALESCE(updated_at, created_at, now()),
                'locked_at', COALESCE(updated_at, created_at, now()), 'minor_unit_precision', 2
            )
        WHERE currency = 'INR' AND fx_rate_snapshot IS NULL
    """)
    op.execute("""
        UPDATE payroll_run_employees
        SET gross_base_paise = gross_earnings_paise,
            total_deductions_base_paise = total_deductions_paise,
            net_base_paise = net_pay_paise
        WHERE gross_base_paise = 0 AND total_deductions_base_paise = 0 AND net_base_paise = 0
    """)
    op.execute("""
        UPDATE payslips
        SET gross_base_paise = CAST(round(gross_earnings * 100) AS bigint),
            total_deductions_base_paise = CAST(round(total_deductions * 100) AS bigint),
            net_base_paise = CAST(round(net_pay * 100) AS bigint)
        WHERE currency = 'INR' AND gross_base_paise = 0 AND total_deductions_base_paise = 0 AND net_base_paise = 0
    """)

    op.create_table(
        "workforce_plans",
        sa.Column("fiscal_year", sa.String(length=9), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=False),
        sa.Column("approved_headcount", sa.Integer(), nullable=False),
        sa.Column("annual_hiring_budget_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'APPROVED'")),
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk("workforce_plans", "company_id", "companies", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workforce_plans")),
        sa.UniqueConstraint("company_id", "fiscal_year", "department", name="uq_workforce_plan_company_year_department"),
    )
    op.create_index("ix_workforce_plans_company_year", "workforce_plans", ["company_id", "fiscal_year"], unique=False)

    op.create_table(
        "org_twin_simulations",
        sa.Column("scenario_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("baseline_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=False),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk("org_twin_simulations", "company_id", "companies", "CASCADE"),
        _fk("org_twin_simulations", "created_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_twin_simulations")),
    )
    op.create_index("ix_org_twin_simulations_company_created", "org_twin_simulations", ["company_id", "created_at"], unique=False)

    op.create_table(
        "marketplace_integrations",
        sa.Column("connector_code", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'DISABLED'")),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk("marketplace_integrations", "company_id", "companies", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_integrations")),
        sa.UniqueConstraint("company_id", "connector_code", name="uq_marketplace_integration_company_connector"),
    )
    op.create_index("ix_marketplace_integrations_company_status", "marketplace_integrations", ["company_id", "status"], unique=False)

    op.create_table(
        "integration_sync_logs",
        sa.Column("integration_id", _uuid(), nullable=False),
        sa.Column("connector_code", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False, server_default=sa.text("'MANUAL'")),
        sa.Column("records_received", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_accepted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("records_rejected", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("health_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk("integration_sync_logs", "integration_id", "marketplace_integrations", "CASCADE"),
        _fk("integration_sync_logs", "company_id", "companies", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_sync_logs")),
    )
    op.create_index("ix_integration_sync_logs_company_connector", "integration_sync_logs", ["company_id", "connector_code", "created_at"], unique=False)
    op.create_index("ix_integration_sync_logs_integration", "integration_sync_logs", ["integration_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("integration_sync_logs")
    op.drop_table("marketplace_integrations")
    op.drop_table("org_twin_simulations")
    op.drop_table("workforce_plans")

    _drop_columns("payslips", ["currency", "gross_base_paise", "total_deductions_base_paise", "net_base_paise"])
    _drop_columns("payroll_run_employees", ["gross_base_paise", "total_deductions_base_paise", "net_base_paise"])
    _drop_columns("payroll_runs", [
        "currency", "base_currency", "country_code", "fx_rate_to_base",
        "fx_rate_snapshot", "fx_rate_locked_at", "statutory_rules_snapshot",
        "statutory_rule_version", "total_gross_base_paise",
        "total_deductions_base_paise", "total_net_base_paise",
    ])
    for table in ("compensations", "salary_structures"):
        _drop_columns(table, ["currency", "fx_rate_to_inr"])
    _drop_columns("employee_risk_assessments", [
        "flight_risk_score", "risk_factors_json", "retention_playbook_json",
        "compa_ratio", "tenure_months", "months_since_promotion",
        "manager_attrition_pct", "model_version",
    ])
    _drop_columns("applications", ["voluntary_demographics", "diversity_consent_at"])
    op.drop_column("employees", "last_promotion_date")
    op.drop_constraint("uq_companies_custom_domain", "companies", type_="unique")
    _drop_columns("companies", [
        "custom_domain", "whitelabel_enabled", "brand_display_name",
        "brand_primary_color", "brand_secondary_color", "brand_logo_url",
        "brand_favicon_url", "email_sender_name", "email_sender_address",
        "email_reply_to", "branded_pdf_header_text",
    ])
