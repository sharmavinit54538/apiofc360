"""Add Employee Wellness AI tables

Revision ID: 9a0b3f7464e6
Revises: 403333c2eb75
Create Date: 2026-07-06 10:15:42.149965

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a0b3f7464e6'
down_revision: Union[str, None] = '403333c2eb75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create employee_wellness_logs table
    op.create_table(
        'employee_wellness_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('mood_score', sa.Integer(), nullable=False),
        sa.Column('stress_level', sa.String(length=20), nullable=False),
        sa.Column('sleep_hours', sa.Numeric(precision=3, scale=1), nullable=False),
        sa.Column('burnout_detected', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('logged_at', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_wellness_logs_employee_id', 'employee_wellness_logs', ['employee_id'], unique=False)

    # 2. create wellness_escalation_rules table
    op.create_table(
        'wellness_escalation_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('min_mood_score', sa.Integer(), server_default='3', nullable=False),
        sa.Column('stress_trigger_level', sa.String(length=20), server_default='HIGH', nullable=False),
        sa.Column('action_type', sa.String(length=50), server_default='ALERT_HR', nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_wellness_rules_company_id', 'wellness_escalation_rules', ['company_id'], unique=False)

    # 3. create wellness_anonymous_chat_sessions table
    op.create_table(
        'wellness_anonymous_chat_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('alias_name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. create wellness_anonymous_chat_messages table
    op.create_table(
        'wellness_anonymous_chat_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('sender_role', sa.String(length=20), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('sentiment_score', sa.Numeric(precision=3, scale=2), server_default='0.00', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['wellness_anonymous_chat_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('wellness_anonymous_chat_messages')
    op.drop_table('wellness_anonymous_chat_sessions')
    op.drop_index('ix_wellness_rules_company_id', table_name='wellness_escalation_rules')
    op.drop_table('wellness_escalation_rules')
    op.drop_index('ix_wellness_logs_employee_id', table_name='employee_wellness_logs')
    op.drop_table('employee_wellness_logs')
