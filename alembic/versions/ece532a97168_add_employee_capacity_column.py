"""add_employee_capacity_column

Revision ID: ece532a97168
Revises: 8b617e0055bf
Create Date: 2026-08-08 19:00:00.257606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ece532a97168'
down_revision: Union[str, None] = '8b617e0055bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy import inspect


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    
    emp_cols = [c['name'] for c in inspector.get_columns('employees')]
    if 'employee_capacity' not in emp_cols:
        op.add_column('employees', sa.Column('employee_capacity', sa.Integer(), nullable=True, server_default=sa.text('100')))

    dept_cols = [c['name'] for c in inspector.get_columns('departments')]
    if 'employee_capacity' not in dept_cols:
        op.add_column('departments', sa.Column('employee_capacity', sa.Integer(), nullable=True, server_default=sa.text('100')))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    
    emp_cols = [c['name'] for c in inspector.get_columns('employees')]
    if 'employee_capacity' in emp_cols:
        op.drop_column('employees', 'employee_capacity')
        
    dept_cols = [c['name'] for c in inspector.get_columns('departments')]
    if 'employee_capacity' in dept_cols:
        op.drop_column('departments', 'employee_capacity')