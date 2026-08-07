"""Add support tickets tables

Revision ID: da4e07c0b748
Revises: 44ddb61b2566
Create Date: 2026-07-05 11:03:27.190410

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da4e07c0b748'
down_revision: Union[str, None] = '44ddb61b2566'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create support_tickets table
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=True),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.String(length=20), server_default='MEDIUM', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='OPEN', nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('assigned_to', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_support_tickets_employee', 'support_tickets', ['employee_id'], unique=False)
    op.create_index('ix_support_tickets_status', 'support_tickets', ['status'], unique=False)
    op.create_index('ix_support_tickets_category', 'support_tickets', ['category'], unique=False)

    # 2. Create support_ticket_updates table
    op.create_table(
        'support_ticket_updates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ticket_id', sa.UUID(), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('update_text', sa.Text(), nullable=False),
        sa.Column('status_changed_to', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ticket_updates_ticket', 'support_ticket_updates', ['ticket_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ticket_updates_ticket', table_name='support_ticket_updates')
    op.drop_table('support_ticket_updates')
    op.drop_index('ix_support_tickets_category', table_name='support_tickets')
    op.drop_index('ix_support_tickets_status', table_name='support_tickets')
    op.drop_index('ix_support_tickets_employee', table_name='support_tickets')
    op.drop_table('support_tickets')
