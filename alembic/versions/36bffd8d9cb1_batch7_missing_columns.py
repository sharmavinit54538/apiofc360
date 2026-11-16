"""batch7_missing_columns

Revision ID: 36bffd8d9cb1
Revises: 36bffd8d9cb0
Create Date: 2026-11-15

Add missing Batch 7 (P3 differentiators) columns and tables that were not applied
to the database. The database was stamped to a later revision without running
these migrations.

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb1'
down_revision: Union[str, None] = '36bffd8d9cb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _fk(table, column, target, ondelete=None):
    kwargs = {"ondelete": ondelete} if ondelete else {}
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"), **kwargs,
    )


def _add_column_if_not_exists(table, column):
    """Add a column only if it doesn't already exist."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns(table)]
    if column.name not in existing_columns:
        op.add_column(table, column)


def _create_table_if_not_exists(table_name, *columns, **kwargs):
    """Create a table only if it doesn't already exist."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table_name not in inspector.get_table_names():
        op.create_table(table_name, *columns, **kwargs)


def _create_index_if_missing(name, table, columns, unique=False):
    """Earlier full-schema migrations may already own these exact indexes."""
    existing = next((index for index in sa.inspect(op.get_bind()).get_indexes(table)
                     if index['name'] == name), None)
    if existing is not None:
        if existing['column_names'] != columns or bool(existing['unique']) != unique:
            raise RuntimeError(f"Existing index {name} has an incompatible definition")
        return
    op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    # =========================================================================
    # attendance_regularization_requests
    # =========================================================================
    _add_column_if_not_exists("attendance_regularization_requests",
        sa.Column("auto_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_not_exists("attendance_regularization_requests",
        sa.Column("exception_reasons", sa.JSON(), nullable=True))
    _add_column_if_not_exists("attendance_regularization_requests",
        sa.Column("policy_trace_json", sa.JSON(), nullable=True))

    # =========================================================================
    # employee_leave_policies
    # =========================================================================
    _add_column_if_not_exists("employee_leave_policies",
        sa.Column("auto_approve_enabled", sa.Boolean(), nullable=True))
    _add_column_if_not_exists("employee_leave_policies",
        sa.Column("max_auto_approve_days", sa.Numeric(6, 2), nullable=True))
    _add_column_if_not_exists("employee_leave_policies",
        sa.Column("min_advance_notice_days", sa.Integer(), nullable=True))
    _add_column_if_not_exists("employee_leave_policies",
        sa.Column("max_team_absent_pct", sa.Numeric(5, 2), nullable=True))
    _add_column_if_not_exists("employee_leave_policies",
        sa.Column("check_holiday_roster_clash", sa.Boolean(), nullable=True))
    _add_column_if_not_exists("employee_leave_policies",
        sa.Column("sandwich_rule_enabled", sa.Boolean(), nullable=True))

    # =========================================================================
    # leave_policies
    # =========================================================================
    _add_column_if_not_exists("leave_policies",
        sa.Column("auto_approve_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_not_exists("leave_policies",
        sa.Column("max_auto_approve_days", sa.Numeric(6, 2), nullable=False, server_default=sa.text("3")))
    _add_column_if_not_exists("leave_policies",
        sa.Column("min_advance_notice_days", sa.Integer(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("leave_policies",
        sa.Column("max_team_absent_pct", sa.Numeric(5, 2), nullable=False, server_default=sa.text("100")))
    _add_column_if_not_exists("leave_policies",
        sa.Column("check_holiday_roster_clash", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    _add_column_if_not_exists("leave_policies",
        sa.Column("sandwich_rule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # =========================================================================
    # leave_requests
    # =========================================================================
    _add_column_if_not_exists("leave_requests",
        sa.Column("auto_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_not_exists("leave_requests",
        sa.Column("exception_reasons", sa.JSON(), nullable=True))
    _add_column_if_not_exists("leave_requests",
        sa.Column("policy_trace_json", sa.JSON(), nullable=True))
    _add_column_if_not_exists("leave_requests",
        sa.Column("approval_source", sa.String(length=30), nullable=True))

    # =========================================================================
    # companies
    # =========================================================================
    _add_column_if_not_exists("companies",
        sa.Column("custom_domain", sa.String(length=255), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("whitelabel_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_not_exists("companies",
        sa.Column("brand_display_name", sa.String(length=150), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("brand_primary_color", sa.String(length=7), nullable=False, server_default=sa.text("'#17365D'")))
    _add_column_if_not_exists("companies",
        sa.Column("brand_secondary_color", sa.String(length=7), nullable=False, server_default=sa.text("'#EAF2F8'")))
    _add_column_if_not_exists("companies",
        sa.Column("brand_logo_url", sa.String(length=500), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("brand_favicon_url", sa.String(length=500), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("email_sender_name", sa.String(length=150), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("email_sender_address", sa.String(length=255), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("email_reply_to", sa.String(length=255), nullable=True))
    _add_column_if_not_exists("companies",
        sa.Column("branded_pdf_header_text", sa.String(length=300), nullable=True))

    # Add unique constraint on custom_domain if not exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    constraints = inspector.get_unique_constraints("companies")
    has_custom_domain_unique = any(c['name'] == 'uq_companies_custom_domain' for c in constraints)
    if not has_custom_domain_unique:
        op.create_unique_constraint("uq_companies_custom_domain", "companies", ["custom_domain"])

    # =========================================================================
    # employees
    # =========================================================================
    _add_column_if_not_exists("employees",
        sa.Column("last_promotion_date", sa.Date(), nullable=True))

    # =========================================================================
    # applications
    # =========================================================================
    _add_column_if_not_exists("applications",
        sa.Column("voluntary_demographics", sa.JSON(), nullable=True))
    _add_column_if_not_exists("applications",
        sa.Column("diversity_consent_at", sa.DateTime(timezone=True), nullable=True))

    # =========================================================================
    # employee_risk_assessments
    # =========================================================================
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("flight_risk_score", sa.Integer(), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("risk_factors_json", sa.JSON(), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("retention_playbook_json", sa.JSON(), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("compa_ratio", sa.Numeric(8, 4), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("tenure_months", sa.Integer(), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("months_since_promotion", sa.Integer(), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("manager_attrition_pct", sa.Numeric(7, 2), nullable=True))
    _add_column_if_not_exists("employee_risk_assessments",
        sa.Column("model_version", sa.String(length=50), nullable=True))

    # =========================================================================
    # salary_structures, compensations
    # =========================================================================
    for table in ("salary_structures", "compensations"):
        _add_column_if_not_exists(table,
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")))
        _add_column_if_not_exists(table,
            sa.Column("fx_rate_to_inr", sa.Numeric(20, 8), nullable=False, server_default=sa.text("1")))

    # =========================================================================
    # payroll_runs
    # =========================================================================
    _add_column_if_not_exists("payroll_runs",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("base_currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default=sa.text("'IN'")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("fx_rate_to_base", sa.Numeric(20, 8), nullable=False, server_default=sa.text("1")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("fx_rate_snapshot", sa.JSON(), nullable=True))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("fx_rate_locked_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("statutory_rules_snapshot", sa.JSON(), nullable=True))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("statutory_rule_version", sa.String(length=100), nullable=False, server_default=sa.text("'IN_LEGACY_STATUTORY_SERVICE'")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("total_gross_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("total_deductions_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payroll_runs",
        sa.Column("total_net_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))

    # =========================================================================
    # payroll_run_employees
    # =========================================================================
    _add_column_if_not_exists("payroll_run_employees",
        sa.Column("gross_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payroll_run_employees",
        sa.Column("total_deductions_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payroll_run_employees",
        sa.Column("net_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))

    # =========================================================================
    # payslips
    # =========================================================================
    _add_column_if_not_exists("payslips",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'")))
    _add_column_if_not_exists("payslips",
        sa.Column("gross_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payslips",
        sa.Column("total_deductions_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payslips",
        sa.Column("net_base_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0")))
    _add_column_if_not_exists("payslips",
        sa.Column("whatsapp_status", sa.String(length=20), nullable=False, server_default=sa.text("'NOT_SENT'")))
    _add_column_if_not_exists("payslips",
        sa.Column("whatsapp_sent_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_not_exists("payslips",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_not_exists("payslips",
        sa.Column("delivery_error", sa.Text(), nullable=True))
    _add_column_if_not_exists("payslips",
        sa.Column("is_password_protected", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_column_if_not_exists("payslips",
        sa.Column("password_rule", sa.String(length=100), nullable=True))

    # =========================================================================
    # Create new tables from Batch 7
    # =========================================================================

    # workforce_plans
    _create_table_if_not_exists("workforce_plans",
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
    _create_index_if_missing("ix_workforce_plans_company_year", "workforce_plans", ["company_id", "fiscal_year"], unique=False)

    # org_twin_simulations
    _create_table_if_not_exists("org_twin_simulations",
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
    _create_index_if_missing("ix_org_twin_simulations_company_created", "org_twin_simulations", ["company_id", "created_at"], unique=False)

    # marketplace_integrations
    _create_table_if_not_exists("marketplace_integrations",
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
    _create_index_if_missing("ix_marketplace_integrations_company_status", "marketplace_integrations", ["company_id", "status"], unique=False)

    # integration_sync_logs
    _create_table_if_not_exists("integration_sync_logs",
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
    _create_index_if_missing("ix_integration_sync_logs_company_connector", "integration_sync_logs", ["company_id", "connector_code", "created_at"], unique=False)
    _create_index_if_missing("ix_integration_sync_logs_integration", "integration_sync_logs", ["integration_id", "created_at"], unique=False)

    # Backfill payroll data for existing INR rows
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


def downgrade() -> None:
    # Drop new tables
    op.drop_table("integration_sync_logs")
    op.drop_table("marketplace_integrations")
    op.drop_table("org_twin_simulations")
    op.drop_table("workforce_plans")

    # Drop columns from payslips
    for col in ["currency", "gross_base_paise", "total_deductions_base_paise", "net_base_paise",
                "whatsapp_status", "whatsapp_sent_at", "sent_at", "delivery_error",
                "is_password_protected", "password_rule"]:
        _drop_column_if_exists("payslips", col)

    # Drop columns from payroll_run_employees
    for col in ["gross_base_paise", "total_deductions_base_paise", "net_base_paise"]:
        _drop_column_if_exists("payroll_run_employees", col)

    # Drop columns from payroll_runs
    for col in ["currency", "base_currency", "country_code", "fx_rate_to_base",
                "fx_rate_snapshot", "fx_rate_locked_at", "statutory_rules_snapshot",
                "statutory_rule_version", "total_gross_base_paise",
                "total_deductions_base_paise", "total_net_base_paise"]:
        _drop_column_if_exists("payroll_runs", col)

    # Drop columns from salary_structures, compensations
    for table in ("compensations", "salary_structures"):
        for col in ["currency", "fx_rate_to_inr"]:
            _drop_column_if_exists(table, col)

    # Drop columns from employee_risk_assessments
    for col in ["flight_risk_score", "risk_factors_json", "retention_playbook_json",
                "compa_ratio", "tenure_months", "months_since_promotion",
                "manager_attrition_pct", "model_version"]:
        _drop_column_if_exists("employee_risk_assessments", col)

    # Drop columns from applications
    for col in ["voluntary_demographics", "diversity_consent_at"]:
        _drop_column_if_exists("applications", col)

    # Drop column from employees
    _drop_column_if_exists("employees", "last_promotion_date")

    # Drop columns from companies
    op.drop_constraint("uq_companies_custom_domain", "companies", type_="unique")
    for col in ["custom_domain", "whitelabel_enabled", "brand_display_name",
                "brand_primary_color", "brand_secondary_color", "brand_logo_url",
                "brand_favicon_url", "email_sender_name", "email_sender_address",
                "email_reply_to", "branded_pdf_header_text"]:
        _drop_column_if_exists("companies", col)

    # Drop columns from attendance_regularization_requests
    for col in ["auto_approved", "exception_reasons", "policy_trace_json"]:
        _drop_column_if_exists("attendance_regularization_requests", col)

    # Drop columns from employee_leave_policies
    for col in ["auto_approve_enabled", "max_auto_approve_days", "min_advance_notice_days",
                "max_team_absent_pct", "check_holiday_roster_clash", "sandwich_rule_enabled"]:
        _drop_column_if_exists("employee_leave_policies", col)

    # Drop columns from leave_policies
    for col in ["auto_approve_enabled", "max_auto_approve_days", "min_advance_notice_days",
                "max_team_absent_pct", "check_holiday_roster_clash", "sandwich_rule_enabled"]:
        _drop_column_if_exists("leave_policies", col)

    # Drop columns from leave_requests
    for col in ["auto_approved", "exception_reasons", "policy_trace_json", "approval_source"]:
        _drop_column_if_exists("leave_requests", col)


def _drop_column_if_exists(table, column_name):
    """Drop a column only if it exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns(table)]
    if column_name in existing_columns:
        op.drop_column(table, column_name)
