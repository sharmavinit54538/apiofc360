"""add_shift_change_requests

Revision ID: 950ee9372060
Revises: 8fd24d8c0797
Create Date: 2026-10-12 08:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text


revision: str = '950ee9372060'
down_revision: Union[str, None] = '8fd24d8c0797'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create shift_change_requests table
    op.create_table(
        'shift_change_requests',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('current_shift_id', UUID(as_uuid=True), nullable=True),
        sa.Column('requested_shift_id', UUID(as_uuid=True), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('reviewed_by', UUID(as_uuid=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['current_shift_id'], ['shifts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['requested_shift_id'], ['shifts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_shift_change_company_status', 'shift_change_requests', ['company_id', 'status'])
    op.create_index('ix_shift_change_employee_created', 'shift_change_requests', ['employee_id', 'created_at'])
    op.create_index('ix_shift_change_status', 'shift_change_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_shift_change_status', table_name='shift_change_requests')
    op.drop_index('ix_shift_change_employee_created', table_name='shift_change_requests')
    op.drop_index('ix_shift_change_company_status', table_name='shift_change_requests')
    op.drop_table('shift_change_requests')