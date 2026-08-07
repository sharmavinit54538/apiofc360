"""Add AI Workflow automation tables

Revision ID: eedfbcfcb2ff
Revises: 9bf51e241d23
Create Date: 2026-07-06 10:01:04.559244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eedfbcfcb2ff'
down_revision: Union[str, None] = '9bf51e241d23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create hr_workflow_definitions table
    op.create_table(
        'hr_workflow_definitions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('trigger_event', sa.String(length=50), nullable=False),
        sa.Column('rule_criteria', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 2. create hr_workflow_instances table
    op.create_table(
        'hr_workflow_instances',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_definition_id', sa.UUID(), nullable=False),
        sa.Column('context_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('current_step_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workflow_definition_id'], ['hr_workflow_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_hr_workflow_instances_definition', 'hr_workflow_instances', ['workflow_definition_id'], unique=False)
    op.create_index('ix_hr_workflow_instances_status', 'hr_workflow_instances', ['status'], unique=False)

    # 3. create hr_workflow_step_instances table
    op.create_table(
        'hr_workflow_step_instances',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workflow_instance_id', sa.UUID(), nullable=False),
        sa.Column('step_name', sa.String(length=150), nullable=False),
        sa.Column('step_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('assigned_to_user_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('decision_recommendation', sa.String(length=30), nullable=True),
        sa.Column('decision_justification', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assigned_to_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workflow_instance_id'], ['hr_workflow_instances.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('hr_workflow_step_instances')
    op.drop_index('ix_hr_workflow_instances_status', table_name='hr_workflow_instances')
    op.drop_index('ix_hr_workflow_instances_definition', table_name='hr_workflow_instances')
    op.drop_table('hr_workflow_instances')
    op.drop_table('hr_workflow_definitions')
