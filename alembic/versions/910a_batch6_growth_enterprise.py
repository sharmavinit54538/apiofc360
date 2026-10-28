"""Batch 6: P2 growth and enterprise modules, features 23 through 33.

Revision ID: 910a_batch6_growth_enterprise
Revises: 909a_batch5_employee_experience
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "910a_batch6_growth_enterprise"
down_revision = "909a_batch5_employee_experience"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _fk(table, column, target, ondelete=None, name=None):
    kwargs = {"ondelete": ondelete} if ondelete else {}
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=name or op.f(f"fk_{table}_{column}_{target}"), **kwargs,
    )


def upgrade() -> None:
    op.create_table(
        'bgv_vendors',
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('api_base_url', sa.String(length=500), nullable=False),
        sa.Column('api_token', sa.Text(), nullable=True),
        sa.Column('webhook_secret', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('bgv_vendors', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bgv_vendors")),
        sa.UniqueConstraint('company_id', 'name', name='uq_bgv_vendor_company_name'),
    )
    op.create_table(
        'compensation_bands',
        sa.Column('band_code', sa.String(length=40), nullable=False),
        sa.Column('grade', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('designation', sa.String(length=100), nullable=True),
        sa.Column('min_paise', sa.BigInteger(), nullable=False),
        sa.Column('mid_paise', sa.BigInteger(), nullable=False),
        sa.Column('max_paise', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default=sa.text("'INR'")),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('compensation_bands', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compensation_bands")),
        sa.UniqueConstraint('company_id', 'band_code', name='uq_compensation_band_company_code'),
    )
    op.create_index('ix_compensation_bands_company_grade', 'compensation_bands', ['company_id', 'grade'], unique=False)
    op.create_table(
        'compensation_market_benchmarks',
        sa.Column('grade', sa.String(length=40), nullable=False),
        sa.Column('designation', sa.String(length=100), nullable=False),
        sa.Column('region', sa.String(length=100), nullable=False, server_default=sa.text("'IN'")),
        sa.Column('min_paise', sa.BigInteger(), nullable=False),
        sa.Column('median_paise', sa.BigInteger(), nullable=False),
        sa.Column('max_paise', sa.BigInteger(), nullable=False),
        sa.Column('source', sa.String(length=150), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('compensation_market_benchmarks', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compensation_market_benchmarks")),
        sa.UniqueConstraint('company_id', 'grade', 'designation', 'region', name='uq_comp_market_grade_role_region'),
    )
    op.create_table(
        'department_increment_budgets',
        sa.Column('department', sa.String(length=100), nullable=False),
        sa.Column('fiscal_year', sa.String(length=9), nullable=False),
        sa.Column('budget_paise', sa.BigInteger(), nullable=False),
        sa.Column('modeled_increment_paise', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column('scenario_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('department_increment_budgets', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_department_increment_budgets")),
        sa.UniqueConstraint('company_id', 'department', 'fiscal_year', name='uq_increment_budget_department_year'),
    )
    op.create_table(
        'engagement_peer_recognitions',
        sa.Column('sender_employee_id', _uuid(), nullable=False),
        sa.Column('recipient_employee_id', _uuid(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'APPROVED'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_peer_recognitions', 'sender_employee_id', 'employees', 'CASCADE'),
        _fk('engagement_peer_recognitions', 'recipient_employee_id', 'employees', 'CASCADE'),
        _fk('engagement_peer_recognitions', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_peer_recognitions")),
    )
    op.create_index('ix_peer_recognition_company_recipient', 'engagement_peer_recognitions', ['company_id', 'recipient_employee_id'], unique=False)
    op.create_table(
        'engagement_surveys',
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('frequency', sa.String(length=20), nullable=False, server_default=sa.text("'ONCE'")),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recurrence_parent_id', _uuid(), nullable=True),
        sa.Column('is_anonymous', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('min_group_size', sa.Integer(), nullable=False, server_default=sa.text('5')),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_surveys', 'recurrence_parent_id', 'engagement_surveys', 'SET NULL'),
        _fk('engagement_surveys', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_surveys")),
    )
    op.create_index('ix_engagement_surveys_company_status', 'engagement_surveys', ['company_id', 'status'], unique=False)
    op.create_table(
        'expense_postings',
        sa.Column('employee_id', _uuid(), nullable=True),
        sa.Column('expense_date', sa.Date(), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default=sa.text("'INR'")),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'POSTED'")),
        sa.Column('external_reference', sa.String(length=150), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('expense_postings', 'employee_id', 'employees', 'SET NULL'),
        _fk('expense_postings', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expense_postings")),
        sa.UniqueConstraint('company_id', 'idempotency_key', name='uq_expense_posting_idempotency'),
    )
    op.create_index('ix_expense_postings_company_status', 'expense_postings', ['company_id', 'status'], unique=False)
    op.create_table(
        'gl_account_mappings',
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('source_key', sa.String(length=60), nullable=False),
        sa.Column('account_code', sa.String(length=60), nullable=False),
        sa.Column('account_name', sa.String(length=150), nullable=False),
        sa.Column('account_type', sa.String(length=30), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('gl_account_mappings', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gl_account_mappings")),
        sa.UniqueConstraint('company_id', 'provider', 'source_key', name='uq_gl_mapping_company_provider_key'),
    )
    op.create_table(
        'identity_providers',
        sa.Column('provider_type', sa.String(length=30), nullable=False),
        sa.Column('client_id', sa.String(length=300), nullable=True),
        sa.Column('client_secret', sa.Text(), nullable=True),
        sa.Column('issuer', sa.String(length=500), nullable=True),
        sa.Column('authorization_endpoint', sa.String(length=500), nullable=True),
        sa.Column('token_endpoint', sa.String(length=500), nullable=True),
        sa.Column('jwks_uri', sa.String(length=500), nullable=True),
        sa.Column('saml_sso_url', sa.String(length=500), nullable=True),
        sa.Column('sp_entity_id', sa.String(length=500), nullable=True),
        sa.Column('x509_certificate', sa.Text(), nullable=True),
        sa.Column('allowed_domains', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('identity_providers', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_providers")),
        sa.UniqueConstraint('company_id', 'provider_type', name='uq_identity_provider_company_type'),
    )
    op.create_table(
        'job_board_integrations',
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('api_base_url', sa.String(length=500), nullable=False),
        sa.Column('api_token', sa.Text(), nullable=True),
        sa.Column('webhook_secret', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('job_board_integrations', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_board_integrations")),
        sa.UniqueConstraint('company_id', 'provider', name='uq_job_board_integration_provider'),
    )
    op.create_table(
        'lms_courses',
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_roles', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('target_departments', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('mandatory_for_compliance', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('validity_months', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('lms_courses', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lms_courses")),
        sa.UniqueConstraint('company_id', 'code', name='uq_lms_course_company_code'),
    )
    op.create_index('ix_lms_courses_company_status', 'lms_courses', ['company_id', 'status'], unique=False)
    op.create_table(
        'performance_cycles_v2',
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column('bell_curve_targets', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('performance_cycles_v2', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_cycles_v2")),
        sa.UniqueConstraint('company_id', 'name', name='uq_performance_cycle_v2_company_name'),
    )
    op.create_index('ix_performance_cycles_v2_company_status', 'performance_cycles_v2', ['company_id', 'status'], unique=False)
    op.create_table(
        'scim_groups',
        sa.Column('display_name', sa.String(length=150), nullable=False),
        sa.Column('external_id', sa.String(length=150), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('scim_groups', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scim_groups")),
        sa.UniqueConstraint('company_id', 'display_name', name='uq_scim_group_company_name'),
    )
    op.create_table(
        'sso_assertions',
        sa.Column('assertion_id', sa.String(length=300), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('sso_assertions', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sso_assertions")),
        sa.UniqueConstraint('company_id', 'assertion_id', name='uq_sso_assertion_company_id'),
    )
    op.create_table(
        'succession_critical_roles',
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=False),
        sa.Column('incumbent_employee_id', _uuid(), nullable=True),
        sa.Column('is_critical', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('vacancy_risk_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('business_impact_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('risk_level', sa.String(length=20), nullable=False, server_default=sa.text("'MEDIUM'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('succession_critical_roles', 'incumbent_employee_id', 'employees', 'SET NULL'),
        _fk('succession_critical_roles', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_succession_critical_roles")),
        sa.UniqueConstraint('company_id', 'title', 'department', name='uq_succession_role_title_department'),
    )
    op.create_index('ix_succession_roles_company_risk', 'succession_critical_roles', ['company_id', 'risk_level'], unique=False)
    op.create_table(
        'bgv_webhook_events',
        sa.Column('vendor_id', _uuid(), nullable=False),
        sa.Column('external_event_id', sa.String(length=150), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('bgv_webhook_events', 'vendor_id', 'bgv_vendors', 'CASCADE'),
        _fk('bgv_webhook_events', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bgv_webhook_events")),
        sa.UniqueConstraint('company_id', 'vendor_id', 'external_event_id', name='uq_bgv_webhook_event'),
    )
    op.create_table(
        'employee_compensation_bands',
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('band_id', _uuid(), nullable=False),
        sa.Column('annual_salary_paise', sa.BigInteger(), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('change_reason', sa.String(length=500), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('employee_compensation_bands', 'employee_id', 'employees', 'CASCADE'),
        _fk('employee_compensation_bands', 'band_id', 'compensation_bands', 'RESTRICT'),
        _fk('employee_compensation_bands', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employee_compensation_bands")),
    )
    op.create_index('ix_employee_comp_bands_employee_current', 'employee_compensation_bands', ['employee_id', 'is_current'], unique=False)
    op.create_index('ix_employee_comp_bands_company_band', 'employee_compensation_bands', ['company_id', 'band_id'], unique=False)
    op.create_table(
        'engagement_manager_action_plans',
        sa.Column('survey_id', _uuid(), nullable=True),
        sa.Column('manager_employee_id', _uuid(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('actions_json', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_manager_action_plans', 'survey_id', 'engagement_surveys', 'SET NULL'),
        _fk('engagement_manager_action_plans', 'manager_employee_id', 'employees', 'CASCADE'),
        _fk('engagement_manager_action_plans', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_manager_action_plans")),
    )
    op.create_index('ix_engagement_actions_company_status', 'engagement_manager_action_plans', ['company_id', 'status'], unique=False)
    op.create_table(
        'engagement_questions',
        sa.Column('survey_id', _uuid(), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('question_type', sa.String(length=20), nullable=False),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_questions', 'survey_id', 'engagement_surveys', 'CASCADE'),
        _fk('engagement_questions', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_questions")),
        sa.UniqueConstraint('survey_id', 'sequence_number', name='uq_engagement_question_sequence'),
    )
    op.create_table(
        'engagement_responses',
        sa.Column('survey_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=True),
        sa.Column('respondent_key_hash', sa.String(length=64), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_responses', 'survey_id', 'engagement_surveys', 'CASCADE'),
        _fk('engagement_responses', 'employee_id', 'employees', 'SET NULL'),
        _fk('engagement_responses', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_responses")),
        sa.UniqueConstraint('survey_id', 'respondent_key_hash', name='uq_engagement_survey_respondent'),
    )
    op.create_index('ix_engagement_responses_company_survey', 'engagement_responses', ['company_id', 'survey_id'], unique=False)
    op.create_table(
        'engagement_reward_ledger',
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('recognition_id', _uuid(), nullable=True),
        sa.Column('entry_type', sa.String(length=20), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('reference', sa.String(length=150), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_reward_ledger', 'employee_id', 'employees', 'CASCADE'),
        _fk('engagement_reward_ledger', 'recognition_id', 'engagement_peer_recognitions', 'SET NULL'),
        _fk('engagement_reward_ledger', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_reward_ledger")),
        sa.UniqueConstraint('recognition_id', 'entry_type', name='uq_reward_ledger_recognition_type'),
    )
    op.create_index('ix_reward_ledger_company_employee', 'engagement_reward_ledger', ['company_id', 'employee_id'], unique=False)
    op.create_table(
        'external_identities',
        sa.Column('user_id', _uuid(), nullable=False),
        sa.Column('provider_type', sa.String(length=30), nullable=False),
        sa.Column('external_id', sa.String(length=300), nullable=False),
        sa.Column('attributes_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('external_identities', 'user_id', 'users', 'CASCADE'),
        _fk('external_identities', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identities")),
        sa.UniqueConstraint('company_id', 'provider_type', 'external_id', name='uq_external_identity_provider_id'),
    )
    op.create_index('ix_external_identities_company_user', 'external_identities', ['company_id', 'user_id'], unique=False)
    op.create_table(
        'internal_job_openings',
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=False),
        sa.Column('designation', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('min_tenure_months', sa.Integer(), nullable=False),
        sa.Column('min_performance_score', sa.Numeric(4, 2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('closes_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', _uuid(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('internal_job_openings', 'created_by', 'users', 'SET NULL'),
        _fk('internal_job_openings', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_internal_job_openings")),
    )
    op.create_index('ix_internal_jobs_company_status', 'internal_job_openings', ['company_id', 'status'], unique=False)
    op.create_table(
        'lms_enrollments',
        sa.Column('course_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('assigned_by', _uuid(), nullable=True),
        sa.Column('assignment_reason', sa.String(length=30), nullable=False, server_default=sa.text("'MANUAL'")),
        sa.Column('is_mandatory', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'ASSIGNED'")),
        sa.Column('progress_percentage', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('lms_enrollments', 'course_id', 'lms_courses', 'CASCADE'),
        _fk('lms_enrollments', 'employee_id', 'employees', 'CASCADE'),
        _fk('lms_enrollments', 'assigned_by', 'users', 'SET NULL'),
        _fk('lms_enrollments', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lms_enrollments")),
        sa.UniqueConstraint('course_id', 'employee_id', name='uq_lms_enrollment_course_employee'),
    )
    op.create_index('ix_lms_enrollments_company_status', 'lms_enrollments', ['company_id', 'status'], unique=False)
    op.create_table(
        'lms_modules',
        sa.Column('course_id', _uuid(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content_type', sa.String(length=20), nullable=False),
        sa.Column('content_url', sa.String(length=500), nullable=True),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('lms_modules', 'course_id', 'lms_courses', 'CASCADE'),
        _fk('lms_modules', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lms_modules")),
        sa.UniqueConstraint('course_id', 'sequence_number', name='uq_lms_module_course_sequence'),
    )
    op.create_table(
        'performance_calibration_runs',
        sa.Column('cycle_id', _uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'IN_PROGRESS'")),
        sa.Column('target_distribution', sa.JSON(), nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('started_by', _uuid(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('performance_calibration_runs', 'cycle_id', 'performance_cycles_v2', 'CASCADE'),
        _fk('performance_calibration_runs', 'started_by', 'users', 'SET NULL'),
        _fk('performance_calibration_runs', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_calibration_runs")),
    )
    op.create_index('ix_performance_calibration_company_cycle', 'performance_calibration_runs', ['company_id', 'cycle_id'], unique=False)
    op.create_table(
        'performance_promotion_approvals',
        sa.Column('cycle_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('current_grade', sa.String(length=40), nullable=False),
        sa.Column('target_grade', sa.String(length=40), nullable=False),
        sa.Column('target_band_id', _uuid(), nullable=True),
        sa.Column('recommended_increment_percentage', sa.Numeric(5, 2), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default=sa.text("'PENDING_MANAGER'")),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('requested_by', _uuid(), nullable=True),
        sa.Column('manager_approved_by', _uuid(), nullable=True),
        sa.Column('hr_approved_by', _uuid(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('performance_promotion_approvals', 'cycle_id', 'performance_cycles_v2', 'CASCADE'),
        _fk('performance_promotion_approvals', 'employee_id', 'employees', 'CASCADE'),
        _fk('performance_promotion_approvals', 'target_band_id', 'compensation_bands', 'SET NULL'),
        _fk('performance_promotion_approvals', 'requested_by', 'users', 'SET NULL'),
        _fk('performance_promotion_approvals', 'manager_approved_by', 'users', 'SET NULL'),
        _fk('performance_promotion_approvals', 'hr_approved_by', 'users', 'SET NULL'),
        _fk('performance_promotion_approvals', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_promotion_approvals")),
    )
    op.create_index('ix_promotion_approvals_company_status', 'performance_promotion_approvals', ['company_id', 'status'], unique=False)
    op.create_table(
        'performance_reviews_360',
        sa.Column('cycle_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('reviewer_id', _uuid(), nullable=False),
        sa.Column('review_type', sa.String(length=20), nullable=False),
        sa.Column('rating', sa.Numeric(4, 2), nullable=True),
        sa.Column('calibrated_rating', sa.Numeric(4, 2), nullable=True),
        sa.Column('comments', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('performance_reviews_360', 'cycle_id', 'performance_cycles_v2', 'CASCADE'),
        _fk('performance_reviews_360', 'employee_id', 'employees', 'CASCADE'),
        _fk('performance_reviews_360', 'reviewer_id', 'users', 'CASCADE'),
        _fk('performance_reviews_360', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_performance_reviews_360")),
        sa.UniqueConstraint('cycle_id', 'employee_id', 'reviewer_id', 'review_type', name='uq_performance_360_reviewer'),
    )
    op.create_index('ix_performance_360_company_employee', 'performance_reviews_360', ['company_id', 'employee_id'], unique=False)
    op.create_table(
        'scim_group_members',
        sa.Column('group_id', _uuid(), nullable=False),
        sa.Column('user_id', _uuid(), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('scim_group_members', 'group_id', 'scim_groups', 'CASCADE'),
        _fk('scim_group_members', 'user_id', 'users', 'CASCADE'),
        _fk('scim_group_members', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scim_group_members")),
        sa.UniqueConstraint('group_id', 'user_id', name='uq_scim_group_member'),
    )
    op.create_table(
        'scim_tokens',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('prefix', sa.String(length=20), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', _uuid(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('scim_tokens', 'created_by', 'users', 'SET NULL'),
        _fk('scim_tokens', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scim_tokens")),
        sa.UniqueConstraint('token_hash', name='uq_scim_token_hash'),
    )
    op.create_index('ix_scim_tokens_company_active', 'scim_tokens', ['company_id', 'is_active'], unique=False)
    op.create_table(
        'succession_slates',
        sa.Column('role_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('performance_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('potential_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('skill_coverage_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('readiness_score', sa.Numeric(5, 2), nullable=False),
        sa.Column('readiness_category', sa.String(length=30), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('succession_slates', 'role_id', 'succession_critical_roles', 'CASCADE'),
        _fk('succession_slates', 'employee_id', 'employees', 'CASCADE'),
        _fk('succession_slates', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_succession_slates")),
        sa.UniqueConstraint('role_id', 'employee_id', name='uq_succession_slate_role_employee'),
    )
    op.create_index('ix_succession_slates_company_readiness', 'succession_slates', ['company_id', 'readiness_category'], unique=False)
    op.create_table(
        'tenant_api_keys',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('prefix', sa.String(length=20), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', _uuid(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('tenant_api_keys', 'created_by', 'users', 'SET NULL'),
        _fk('tenant_api_keys', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_api_keys")),
        sa.UniqueConstraint('key_hash', name='uq_tenant_api_key_hash'),
    )
    op.create_index('ix_tenant_api_keys_company_active', 'tenant_api_keys', ['company_id', 'is_active'], unique=False)
    op.create_table(
        'webhook_subscriptions',
        sa.Column('target_url', sa.String(length=500), nullable=False),
        sa.Column('secret_encrypted', sa.Text(), nullable=False),
        sa.Column('events', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('created_by', _uuid(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('webhook_subscriptions', 'created_by', 'users', 'SET NULL'),
        _fk('webhook_subscriptions', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_subscriptions")),
    )
    op.create_index('ix_webhook_subscriptions_company_active', 'webhook_subscriptions', ['company_id', 'is_active'], unique=False)
    op.create_table(
        'engagement_answers',
        sa.Column('response_id', _uuid(), nullable=False),
        sa.Column('question_id', _uuid(), nullable=False),
        sa.Column('numeric_value', sa.Numeric(5, 2), nullable=True),
        sa.Column('text_value', sa.Text(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('engagement_answers', 'response_id', 'engagement_responses', 'CASCADE'),
        _fk('engagement_answers', 'question_id', 'engagement_questions', 'CASCADE'),
        _fk('engagement_answers', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_answers")),
        sa.UniqueConstraint('response_id', 'question_id', name='uq_engagement_answer_question'),
    )
    op.create_table(
        'gl_reconciliation_reports',
        sa.Column('period_id', _uuid(), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('internal_total_paise', sa.BigInteger(), nullable=False),
        sa.Column('external_total_paise', sa.BigInteger(), nullable=False),
        sa.Column('difference_paise', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('gl_reconciliation_reports', 'period_id', 'payroll_periods', 'SET NULL'),
        _fk('gl_reconciliation_reports', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gl_reconciliation_reports")),
    )
    op.create_index('ix_gl_reconciliation_company_period', 'gl_reconciliation_reports', ['company_id', 'period_id'], unique=False)
    op.create_table(
        'internal_job_applications',
        sa.Column('opening_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('eligibility_json', sa.JSON(), nullable=False),
        sa.Column('tenure_months_at_application', sa.Integer(), nullable=False),
        sa.Column('performance_score', sa.Numeric(4, 2), nullable=True),
        sa.Column('cover_note', sa.Text(), nullable=True),
        sa.Column('manager_approved_by', _uuid(), nullable=True),
        sa.Column('manager_decision_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('manager_decision_reason', sa.Text(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('internal_job_applications', 'opening_id', 'internal_job_openings', 'CASCADE'),
        _fk('internal_job_applications', 'employee_id', 'employees', 'CASCADE'),
        _fk('internal_job_applications', 'manager_approved_by', 'users', 'SET NULL'),
        _fk('internal_job_applications', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_internal_job_applications")),
        sa.UniqueConstraint('opening_id', 'employee_id', name='uq_internal_job_application_employee'),
    )
    op.create_index('ix_internal_applications_company_status', 'internal_job_applications', ['company_id', 'status'], unique=False)
    op.create_table(
        'job_board_syncs',
        sa.Column('job_id', _uuid(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('external_job_id', sa.String(length=150), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column('request_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('response_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('job_board_syncs', 'job_id', 'jobs', 'CASCADE'),
        _fk('job_board_syncs', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_board_syncs")),
        sa.UniqueConstraint('company_id', 'job_id', 'provider', name='uq_job_board_sync_job_provider'),
    )
    op.create_index('ix_job_board_syncs_company_status', 'job_board_syncs', ['company_id', 'status'], unique=False)
    op.create_table(
        'lms_certificates',
        sa.Column('enrollment_id', _uuid(), nullable=False),
        sa.Column('employee_id', _uuid(), nullable=False),
        sa.Column('certificate_number', sa.String(length=60), nullable=False),
        sa.Column('verification_hash', sa.String(length=64), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('lms_certificates', 'enrollment_id', 'lms_enrollments', 'CASCADE'),
        _fk('lms_certificates', 'employee_id', 'employees', 'CASCADE'),
        _fk('lms_certificates', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lms_certificates")),
        sa.UniqueConstraint('enrollment_id', name='uq_lms_certificate_enrollment'),
        sa.UniqueConstraint('certificate_number', name='uq_lms_certificate_number'),
    )
    op.create_table(
        'lms_module_progress',
        sa.Column('enrollment_id', _uuid(), nullable=False),
        sa.Column('module_id', _uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'NOT_STARTED'")),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('lms_module_progress', 'enrollment_id', 'lms_enrollments', 'CASCADE'),
        _fk('lms_module_progress', 'module_id', 'lms_modules', 'CASCADE'),
        _fk('lms_module_progress', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lms_module_progress")),
        sa.UniqueConstraint('enrollment_id', 'module_id', name='uq_lms_progress_enrollment_module'),
    )
    op.create_table(
        'succession_development_actions',
        sa.Column('slate_id', _uuid(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_employee_id', _uuid(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('progress_percentage', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=30), nullable=False, server_default=sa.text("'NOT_STARTED'")),
        sa.Column('evidence_reference', sa.String(length=500), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('succession_development_actions', 'slate_id', 'succession_slates', 'CASCADE'),
        _fk('succession_development_actions', 'owner_employee_id', 'employees', 'SET NULL'),
        _fk('succession_development_actions', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_succession_development_actions")),
    )
    op.create_index('ix_succession_actions_company_status', 'succession_development_actions', ['company_id', 'status'], unique=False)
    op.create_table(
        'webhook_deliveries',
        sa.Column('subscription_id', _uuid(), nullable=False),
        sa.Column('event_id', sa.String(length=80), nullable=False),
        sa.Column('event_type', sa.String(length=80), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default=sa.text('5')),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('response_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('webhook_deliveries', 'subscription_id', 'webhook_subscriptions', 'CASCADE'),
        _fk('webhook_deliveries', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint('subscription_id', 'event_id', name='uq_webhook_delivery_event'),
    )
    op.create_index('ix_webhook_deliveries_queue', 'webhook_deliveries', ['status', 'next_attempt_at'], unique=False)
    op.create_index('ix_webhook_deliveries_company_status', 'webhook_deliveries', ['company_id', 'status'], unique=False)
    op.create_table(
        'bgv_cases',
        sa.Column('vendor_id', _uuid(), nullable=False),
        sa.Column('candidate_id', _uuid(), nullable=True),
        sa.Column('application_id', _uuid(), nullable=True),
        sa.Column('employee_id', _uuid(), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False, server_default=sa.text("'PENDING_CONSENT'")),
        sa.Column('vendor_reference', sa.String(length=150), nullable=True),
        sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consent_ip_address', sa.String(length=45), nullable=True),
        sa.Column('consent_user_agent', sa.String(length=500), nullable=True),
        sa.Column('consent_text_hash', sa.String(length=64), nullable=True),
        sa.Column('consent_reference', sa.String(length=150), nullable=True),
        sa.Column('created_by', _uuid(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('bgv_cases', 'vendor_id', 'bgv_vendors', 'RESTRICT'),
        _fk('bgv_cases', 'candidate_id', 'candidates', 'SET NULL'),
        _fk('bgv_cases', 'application_id', 'applications', 'SET NULL'),
        _fk('bgv_cases', 'employee_id', 'employees', 'SET NULL'),
        _fk('bgv_cases', 'created_by', 'users', 'SET NULL'),
        _fk('bgv_cases', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bgv_cases")),
    )
    op.create_index('ix_bgv_cases_application', 'bgv_cases', ['application_id'], unique=False)
    op.create_index('ix_bgv_cases_company_status', 'bgv_cases', ['company_id', 'status'], unique=False)
    op.create_table(
        'candidate_sources',
        sa.Column('application_id', _uuid(), nullable=False),
        sa.Column('candidate_id', _uuid(), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('external_candidate_id', sa.String(length=150), nullable=False),
        sa.Column('utm_source', sa.String(length=100), nullable=True),
        sa.Column('utm_medium', sa.String(length=100), nullable=True),
        sa.Column('utm_campaign', sa.String(length=150), nullable=True),
        sa.Column('utm_term', sa.String(length=150), nullable=True),
        sa.Column('utm_content', sa.String(length=150), nullable=True),
        sa.Column('referrer', sa.String(length=500), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('candidate_sources', 'application_id', 'applications', 'CASCADE'),
        _fk('candidate_sources', 'candidate_id', 'candidates', 'SET NULL'),
        _fk('candidate_sources', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_sources")),
        sa.UniqueConstraint('company_id', 'provider', 'external_candidate_id', name='uq_candidate_source_external'),
    )
    op.create_index('ix_candidate_sources_company_utm', 'candidate_sources', ['company_id', 'utm_source', 'utm_medium', 'utm_campaign'], unique=False)
    op.create_table(
        'webhook_delivery_attempts',
        sa.Column('delivery_id', _uuid(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('request_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('signature', sa.String(length=128), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('webhook_delivery_attempts', 'delivery_id', 'webhook_deliveries', 'CASCADE'),
        _fk('webhook_delivery_attempts', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_delivery_attempts")),
        sa.UniqueConstraint('delivery_id', 'attempt_number', name='uq_webhook_delivery_attempt'),
    )
    op.create_table(
        'bgv_checks',
        sa.Column('case_id', _uuid(), nullable=False),
        sa.Column('check_type', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column('vendor_reference', sa.String(length=150), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('discrepancy_flag', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('discrepancy_details', sa.Text(), nullable=True),
        sa.Column('resolution_status', sa.String(length=30), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('resolved_by', _uuid(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', _uuid(), nullable=False),
        sa.Column('company_id', _uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _fk('bgv_checks', 'case_id', 'bgv_cases', 'CASCADE'),
        _fk('bgv_checks', 'resolved_by', 'users', 'SET NULL'),
        _fk('bgv_checks', 'company_id', 'companies', 'CASCADE'),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bgv_checks")),
        sa.UniqueConstraint('case_id', 'check_type', name='uq_bgv_check_case_type'),
    )
    op.create_index('ix_bgv_checks_company_status', 'bgv_checks', ['company_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_table('bgv_checks')
    op.drop_table('webhook_delivery_attempts')
    op.drop_table('candidate_sources')
    op.drop_table('bgv_cases')
    op.drop_table('webhook_deliveries')
    op.drop_table('succession_development_actions')
    op.drop_table('lms_module_progress')
    op.drop_table('lms_certificates')
    op.drop_table('job_board_syncs')
    op.drop_table('internal_job_applications')
    op.drop_table('gl_reconciliation_reports')
    op.drop_table('engagement_answers')
    op.drop_table('webhook_subscriptions')
    op.drop_table('tenant_api_keys')
    op.drop_table('succession_slates')
    op.drop_table('scim_tokens')
    op.drop_table('scim_group_members')
    op.drop_table('performance_reviews_360')
    op.drop_table('performance_promotion_approvals')
    op.drop_table('performance_calibration_runs')
    op.drop_table('lms_modules')
    op.drop_table('lms_enrollments')
    op.drop_table('internal_job_openings')
    op.drop_table('external_identities')
    op.drop_table('engagement_reward_ledger')
    op.drop_table('engagement_responses')
    op.drop_table('engagement_questions')
    op.drop_table('engagement_manager_action_plans')
    op.drop_table('employee_compensation_bands')
    op.drop_table('bgv_webhook_events')
    op.drop_table('succession_critical_roles')
    op.drop_table('sso_assertions')
    op.drop_table('scim_groups')
    op.drop_table('performance_cycles_v2')
    op.drop_table('lms_courses')
    op.drop_table('job_board_integrations')
    op.drop_table('identity_providers')
    op.drop_table('gl_account_mappings')
    op.drop_table('expense_postings')
    op.drop_table('engagement_surveys')
    op.drop_table('engagement_peer_recognitions')
    op.drop_table('department_increment_budgets')
    op.drop_table('compensation_market_benchmarks')
    op.drop_table('compensation_bands')
    op.drop_table('bgv_vendors')
