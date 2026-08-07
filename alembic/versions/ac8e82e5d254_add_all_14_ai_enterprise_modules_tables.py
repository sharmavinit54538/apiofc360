"""Add all 14 AI enterprise modules tables

Revision ID: ac8e82e5d254
Revises: c5b37379742c
Create Date: 2026-07-06 10:41:33.913446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac8e82e5d254'
down_revision: Union[str, None] = 'c5b37379742c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. org_hierarchy_snapshots
    op.create_table('org_hierarchy_snapshots',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('hierarchy_json', sa.Text(), nullable=False),
        sa.Column('department_structure', sa.Text(), nullable=False),
        sa.Column('leadership_map', sa.Text(), nullable=False),
        sa.Column('ai_insights', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_org_snapshots_company_id', 'org_hierarchy_snapshots', ['company_id'])

    # 2. skill_gap_analyses
    op.create_table('skill_gap_analyses',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('target_role', sa.String(100), nullable=False),
        sa.Column('current_skills', sa.Text(), nullable=False),
        sa.Column('required_skills', sa.Text(), nullable=False),
        sa.Column('missing_skills', sa.Text(), nullable=False),
        sa.Column('learning_roadmap', sa.Text(), nullable=True),
        sa.Column('recommended_courses', sa.Text(), nullable=True),
        sa.Column('certification_suggestions', sa.Text(), nullable=True),
        sa.Column('promotion_readiness_score', sa.Integer(), nullable=True),
        sa.Column('hiring_recommendation', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_skill_gap_employee_id', 'skill_gap_analyses', ['employee_id'])

    # 3. shift_plans
    op.create_table('shift_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('department', sa.String(100), nullable=True),
        sa.Column('plan_type', sa.String(30), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('ai_optimization_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_shift_plans_company_id', 'shift_plans', ['company_id'])

    # 4. shift_plan_entries
    op.create_table('shift_plan_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('shift_date', sa.Date(), nullable=False),
        sa.Column('shift_type', sa.String(30), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['shift_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))

    # 5. employee_digital_twins
    op.create_table('employee_digital_twins',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('skills_summary', sa.Text(), nullable=True),
        sa.Column('performance_score', sa.Integer(), nullable=True),
        sa.Column('projects_summary', sa.Text(), nullable=True),
        sa.Column('learning_progress', sa.Text(), nullable=True),
        sa.Column('goals_summary', sa.Text(), nullable=True),
        sa.Column('attendance_score', sa.Integer(), nullable=True),
        sa.Column('leave_utilization', sa.Numeric(5, 2), nullable=True),
        sa.Column('productivity_index', sa.Integer(), nullable=True),
        sa.Column('career_growth_score', sa.Integer(), nullable=True),
        sa.Column('certifications', sa.Text(), nullable=True),
        sa.Column('feedback_summary', sa.Text(), nullable=True),
        sa.Column('ai_performance_forecast', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id'))
    op.create_index('ix_digital_twin_employee_id', 'employee_digital_twins', ['employee_id'])

    # 6. voice_command_logs
    op.create_table('voice_command_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('raw_transcript', sa.Text(), nullable=False),
        sa.Column('parsed_intent', sa.String(100), nullable=True),
        sa.Column('parsed_entities', sa.Text(), nullable=True),
        sa.Column('execution_result', sa.Text(), nullable=True),
        sa.Column('tts_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_voice_logs_company_id', 'voice_command_logs', ['company_id'])

    # 7. mood_detection_logs
    op.create_table('mood_detection_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('input_source', sa.String(30), nullable=False),
        sa.Column('input_text', sa.Text(), nullable=False),
        sa.Column('detected_mood', sa.String(30), nullable=False),
        sa.Column('confidence_score', sa.Integer(), nullable=True),
        sa.Column('wellness_recommendations', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_mood_logs_employee_id', 'mood_detection_logs', ['employee_id'])

    # 8. career_path_predictions
    op.create_table('career_path_predictions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('predicted_next_role', sa.String(100), nullable=True),
        sa.Column('promotion_timeline_months', sa.Integer(), nullable=True),
        sa.Column('skill_roadmap', sa.Text(), nullable=True),
        sa.Column('career_growth_narrative', sa.Text(), nullable=True),
        sa.Column('internal_opportunities', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_career_path_employee_id', 'career_path_predictions', ['employee_id'])

    # 9. learning_recommendations
    op.create_table('learning_recommendations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('target_skill_gap', sa.String(200), nullable=False),
        sa.Column('recommended_courses', sa.Text(), nullable=True),
        sa.Column('recommended_certifications', sa.Text(), nullable=True),
        sa.Column('recommended_videos', sa.Text(), nullable=True),
        sa.Column('recommended_books', sa.Text(), nullable=True),
        sa.Column('recommended_projects', sa.Text(), nullable=True),
        sa.Column('internal_training', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_learning_recs_employee_id', 'learning_recommendations', ['employee_id'])

    # 10. workforce_forecast_runs
    op.create_table('workforce_forecast_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('forecast_period', sa.String(50), nullable=False),
        sa.Column('predicted_hiring_needs', sa.Integer(), nullable=True),
        sa.Column('predicted_attrition_count', sa.Integer(), nullable=True),
        sa.Column('future_skill_demand', sa.Text(), nullable=True),
        sa.Column('salary_budget_estimate', sa.Numeric(16, 2), nullable=True),
        sa.Column('workforce_plan_narrative', sa.Text(), nullable=True),
        sa.Column('department_growth_forecast', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_workforce_forecast_company_id', 'workforce_forecast_runs', ['company_id'])

    # 11. talent_matches
    op.create_table('talent_matches',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('match_type', sa.String(30), nullable=False),
        sa.Column('match_title', sa.String(200), nullable=False),
        sa.Column('match_description', sa.Text(), nullable=True),
        sa.Column('match_score', sa.Numeric(5, 2), nullable=True),
        sa.Column('ai_justification', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_talent_matches_employee_id', 'talent_matches', ['employee_id'])

    # 12. meeting_intelligence_logs
    op.create_table('meeting_intelligence_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('meeting_title', sa.String(200), nullable=False),
        sa.Column('meeting_transcript', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('action_items', sa.Text(), nullable=True),
        sa.Column('decisions', sa.Text(), nullable=True),
        sa.Column('task_assignments', sa.Text(), nullable=True),
        sa.Column('mom', sa.Text(), nullable=True),
        sa.Column('followup_reminders', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_meeting_intel_company_id', 'meeting_intelligence_logs', ['company_id'])

    # 13. compliance_audit_logs
    op.create_table('compliance_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('audit_scope', sa.String(50), nullable=False),
        sa.Column('findings', sa.Text(), nullable=True),
        sa.Column('risk_level', sa.String(20), server_default='LOW', nullable=False),
        sa.Column('recommendations', sa.Text(), nullable=True),
        sa.Column('auto_corrected', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_compliance_audit_company_id', 'compliance_audit_logs', ['company_id'])

    # 14. employee_risk_assessments
    op.create_table('employee_risk_assessments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('resignation_risk_score', sa.Integer(), nullable=True),
        sa.Column('burnout_risk_score', sa.Integer(), nullable=True),
        sa.Column('performance_risk_score', sa.Integer(), nullable=True),
        sa.Column('compliance_risk_score', sa.Integer(), nullable=True),
        sa.Column('engagement_risk_score', sa.Integer(), nullable=True),
        sa.Column('overall_risk_level', sa.String(20), server_default='LOW', nullable=False),
        sa.Column('risk_narrative', sa.Text(), nullable=True),
        sa.Column('recommended_actions', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_risk_assessments_employee_id', 'employee_risk_assessments', ['employee_id'])

    # 15. copilot_query_logs
    op.create_table('copilot_query_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('asked_by_user_id', sa.UUID(), nullable=True),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('ai_response', sa.Text(), nullable=False),
        sa.Column('data_context_used', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asked_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_copilot_logs_company_id', 'copilot_query_logs', ['company_id'])


def downgrade() -> None:
    for tbl in [
        'copilot_query_logs', 'employee_risk_assessments', 'compliance_audit_logs',
        'meeting_intelligence_logs', 'talent_matches', 'workforce_forecast_runs',
        'learning_recommendations', 'career_path_predictions', 'mood_detection_logs',
        'voice_command_logs', 'employee_digital_twins', 'shift_plan_entries',
        'shift_plans', 'skill_gap_analyses', 'org_hierarchy_snapshots',
    ]:
        op.drop_table(tbl)
