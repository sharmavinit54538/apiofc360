"""add_employee_hierarchy_and_audit

Revision ID: f533d8a18648
Revises: f433d8a18647
Create Date: 2026-07-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f533d8a18648'
down_revision: Union[str, None] = '426a11878947'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add manager_id to employees table
    op.add_column('employees', sa.Column('manager_id', sa.UUID(), nullable=True))
    
    # 2. Create index for manager_id
    op.create_index('ix_employees_manager_id', 'employees', ['manager_id'], unique=False)
    
    # 3. Create foreign key constraint pointing to employees.id
    op.create_foreign_key(
        'fk_employees_manager_id_employees',
        'employees', 'employees',
        ['manager_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # 4. Create check constraint to prevent self-reporting
    op.create_check_constraint(
        'ck_employees_manager_self_report',
        'employees',
        'id != manager_id'
    )
    
    # 5. Create hierarchy_audit_logs table
    op.create_table(
        'hierarchy_audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('previous_manager_id', sa.UUID(), nullable=True),
        sa.Column('new_manager_id', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name='fk_hierarchy_audit_logs_employee_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['previous_manager_id'], ['employees.id'], name='fk_hierarchy_audit_logs_previous_manager_id', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['new_manager_id'], ['employees.id'], name='fk_hierarchy_audit_logs_new_manager_id', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name='fk_hierarchy_audit_logs_updated_by', ondelete='SET NULL'),
    )


def downgrade() -> None:
    # 1. Drop hierarchy_audit_logs table
    op.drop_table('hierarchy_audit_logs')
    
    # 2. Drop check constraint from employees
    op.drop_constraint('ck_employees_manager_self_report', 'employees', type_='check')
    
    # 3. Drop foreign key constraint from employees
    op.drop_constraint('fk_employees_manager_id_employees', 'employees', type_='foreignkey')
    
    # 4. Drop index
    op.drop_index('ix_employees_manager_id', table_name='employees')
    
    # 5. Drop manager_id column from employees
    op.drop_column('employees', 'manager_id')
