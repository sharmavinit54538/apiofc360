"""add_autopilot_performance_training_tables

Revision ID: 0003
Revises: 2d99d31e460b
Create Date: 2026-11-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '2d99d31e460b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Autopilot HR tables
    op.create_table('autopilot_policy_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('priority', sa.Integer(), server_default=sa.text('100'), nullable=False),
        sa.Column('confidence_threshold', sa.Numeric(precision=5, scale=4), server_default=sa.text('0.85'), nullable=False),
        sa.Column('conditions_json', sa.JSON(), nullable=True),
        sa.Column('escalation_ladder_json', sa.JSON(), nullable=True),
        sa.Column('sla_hours', sa.Integer(), server_default=sa.text('24'), nullable=False),
        sa.Column('rule_metadata_json', sa.JSON(), nullable=True),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_autopilot_policy_rules_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_autopilot_policy_rules'))
    )
    op.create_index('ix_autopilot_rules_company_domain', 'autopilot_policy_rules', ['company_id', 'domain'], unique=False)
    op.create_index('ix_autopilot_rules_enabled', 'autopilot_policy_rules', ['enabled'], unique=False)

    op.create_table('autopilot_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rule_id', sa.UUID(), nullable=True),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('decision', sa.String(length=40), nullable=False),
        sa.Column('confidence_score', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('before_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('after_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('policy_trace_json', sa.JSON(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('is_rolled_back', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('rolled_back_by', sa.UUID(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=True),
        sa.Column('rollback_metadata_json', sa.JSON(), nullable=True),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_autopilot_audit_logs_actor_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_autopilot_audit_logs_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rolled_back_by'], ['users.id'], name=op.f('fk_autopilot_audit_logs_rolled_back_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rule_id'], ['autopilot_policy_rules.id'], name=op.f('fk_autopilot_audit_logs_rule_id_autopilot_policy_rules'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_autopilot_audit_logs'))
    )
    op.create_index('ix_autopilot_audit_company_created', 'autopilot_audit_logs', ['company_id', 'created_at'], unique=False)
    op.create_index('ix_autopilot_audit_entity', 'autopilot_audit_logs', ['domain', 'entity_id'], unique=False)

    op.create_table('autopilot_exception_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rule_id', sa.UUID(), nullable=True),
        sa.Column('domain', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('exception_reasons', sa.JSON(), nullable=True),
        sa.Column('policy_trace_json', sa.JSON(), nullable=True),
        sa.Column('confidence_score', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('escalation_level', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('escalation_ladder_json', sa.JSON(), nullable=True),
        sa.Column('assigned_to_user_id', sa.UUID(), nullable=True),
        sa.Column('assigned_role', sa.String(length=50), nullable=True),
        sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sla_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('before_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('after_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to_user_id'], ['users.id'], name=op.f('fk_autopilot_exception_items_assigned_to_user_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_autopilot_exception_items_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rule_id'], ['autopilot_policy_rules.id'], name=op.f('fk_autopilot_exception_items_rule_id_autopilot_policy_rules'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_autopilot_exception_items'))
    )
    op.create_index('ix_autopilot_exceptions_company_status', 'autopilot_exception_items', ['company_id', 'status'], unique=False)
    op.create_index('ix_autopilot_exceptions_sla', 'autopilot_exception_items', ['sla_due_at'], unique=False)

    # Performance Feedback table
    op.create_table('performance_feedback',
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('review_id', sa.UUID(), nullable=True),
        sa.Column('author_id', sa.UUID(), nullable=False),
        sa.Column('feedback_type', sa.String(length=20), nullable=False),
        sa.Column('rating', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column('strengths', sa.Text(), nullable=False),
        sa.Column('improvement_areas', sa.Text(), nullable=False),
        sa.Column('comments', sa.Text(), nullable=True),
        sa.Column('confidential', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_performance_feedback_author_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_performance_feedback_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_performance_feedback_employee_id_employees'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['review_id'], ['performance_reviews.id'], name=op.f('fk_performance_feedback_review_id_performance_reviews'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_feedback'))
    )
    op.create_index('ix_performance_feedback_employee_id', 'performance_feedback', ['employee_id'], unique=False)
    op.create_index('ix_performance_feedback_review_id', 'performance_feedback', ['review_id'], unique=False)

    # Performance Rewards table
    op.create_table('performance_rewards',
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('review_id', sa.UUID(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('reward_type', sa.String(length=30), nullable=False),
        sa.Column('monetary_value', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('approval_required', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('approved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_performance_rewards_approved_by_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_performance_rewards_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_performance_rewards_employee_id_employees'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['review_id'], ['performance_reviews.id'], name=op.f('fk_performance_rewards_review_id_performance_reviews'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_performance_rewards'))
    )
    op.create_index('ix_performance_rewards_employee_id', 'performance_rewards', ['employee_id'], unique=False)
    op.create_index('ix_performance_rewards_review_id', 'performance_rewards', ['review_id'], unique=False)

    # Training Courses table
    op.create_table('training_courses',
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_hours', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_training_courses_company_id_companies'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_training_courses'))
    )
    op.create_index('ix_training_courses_company_id', 'training_courses', ['company_id'], unique=False)

    # Training Assignments table
    op.create_table('training_assignments',
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('training_id', sa.UUID(), nullable=False),
        sa.Column('assigned_by', sa.UUID(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('priority', sa.String(length=20), server_default=sa.text("'medium'"), nullable=False),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'assigned'"), nullable=False),
        sa.Column('progress', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('review_id', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], name=op.f('fk_training_assignments_assigned_by_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_training_assignments_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_training_assignments_employee_id_employees'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['review_id'], ['performance_reviews.id'], name=op.f('fk_training_assignments_review_id_performance_reviews'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['training_id'], ['training_courses.id'], name=op.f('fk_training_assignments_training_id_training_courses'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_training_assignments'))
    )
    op.create_index('ix_training_assignments_employee_id', 'training_assignments', ['employee_id'], unique=False)
    op.create_index('ix_training_assignments_status', 'training_assignments', ['status'], unique=False)
    op.create_index('ix_training_assignments_training_id', 'training_assignments', ['training_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_training_assignments_training_id', table_name='training_assignments')
    op.drop_index('ix_training_assignments_status', table_name='training_assignments')
    op.drop_index('ix_training_assignments_employee_id', table_name='training_assignments')
    op.drop_table('training_assignments')
    op.drop_index('ix_training_courses_company_id', table_name='training_courses')
    op.drop_table('training_courses')
    op.drop_index('ix_performance_rewards_review_id', table_name='performance_rewards')
    op.drop_index('ix_performance_rewards_employee_id', table_name='performance_rewards')
    op.drop_table('performance_rewards')
    op.drop_index('ix_performance_feedback_review_id', table_name='performance_feedback')
    op.drop_index('ix_performance_feedback_employee_id', table_name='performance_feedback')
    op.drop_table('performance_feedback')
    op.drop_index('ix_autopilot_exceptions_sla', table_name='autopilot_exception_items')
    op.drop_index('ix_autopilot_exceptions_company_status', table_name='autopilot_exception_items')
    op.drop_table('autopilot_exception_items')
    op.drop_index('ix_autopilot_audit_entity', table_name='autopilot_audit_logs')
    op.drop_index('ix_autopilot_audit_company_created', table_name='autopilot_audit_logs')
    op.drop_table('autopilot_audit_logs')
    op.drop_index('ix_autopilot_rules_enabled', table_name='autopilot_policy_rules')
    op.drop_index('ix_autopilot_rules_company_domain', table_name='autopilot_policy_rules')
    op.drop_table('autopilot_policy_rules')
    op.drop_index('ix_training_courses_company_id', table_name='training_courses')
    op.drop_table('training_courses')