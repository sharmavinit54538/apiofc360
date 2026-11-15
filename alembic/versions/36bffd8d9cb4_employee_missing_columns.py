"""employee_missing_columns

Revision ID: 36bffd8d9cb4
Revises: 36bffd8d9cb3
Create Date: 2026-11-15

Add missing Employee columns that were not applied because the database was
stamped to a later revision without running all intermediate migrations.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb4'
down_revision: Union[str, None] = '36bffd8d9cb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add missing Employee columns
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]

    # branch_id - FK to branches
    if 'branch_id' not in existing_columns:
        op.add_column('employees', sa.Column('branch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('branches.id', ondelete='SET NULL'), nullable=True))

    # legal_entity_id - FK to legal_entities
    if 'legal_entity_id' not in existing_columns:
        op.add_column('employees', sa.Column('legal_entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('legal_entities.id', ondelete='SET NULL'), nullable=True))

    # State code for PF/ESI
    if 'state_code' not in existing_columns:
        op.add_column('employees', sa.Column('state_code', sa.String(length=2), nullable=True))

    # PF/ESI fields
    if 'pf_membership_active' not in existing_columns:
        op.add_column('employees', sa.Column('pf_membership_active', sa.Boolean(), nullable=False, default=True, server_default=sa.text('true')))
    if 'is_eps_eligible' not in existing_columns:
        op.add_column('employees', sa.Column('is_eps_eligible', sa.Boolean(), nullable=False, default=True, server_default=sa.text('true')))
    if 'pf_higher_wage_opted' not in existing_columns:
        op.add_column('employees', sa.Column('pf_higher_wage_opted', sa.Boolean(), nullable=False, default=False, server_default=sa.text('false')))
    if 'eps_higher_wage_opted' not in existing_columns:
        op.add_column('employees', sa.Column('eps_higher_wage_opted', sa.Boolean(), nullable=False, default=False, server_default=sa.text('false')))
    if 'vpf_rate' not in existing_columns:
        op.add_column('employees', sa.Column('vpf_rate', sa.Numeric(7, 6), nullable=False, default=sa.text('0'), server_default=sa.text('0')))
    if 'is_pwd' not in existing_columns:
        op.add_column('employees', sa.Column('is_pwd', sa.Boolean(), nullable=False, default=False, server_default=sa.text('false')))
    if 'esi_covered_at_period_start' not in existing_columns:
        op.add_column('employees', sa.Column('esi_covered_at_period_start', sa.Boolean(), nullable=False, default=False, server_default=sa.text('false')))

    # Add indexes for the new FK columns if they don't exist
    indexes = inspector.get_indexes('employees')
    existing_index_names = [idx['name'] for idx in indexes]

    if 'ix_employees_branch_id' not in existing_index_names:
        op.create_index('ix_employees_branch_id', 'employees', ['branch_id'], unique=False)
    if 'ix_employees_legal_entity_id' not in existing_index_names:
        op.create_index('ix_employees_legal_entity_id', 'employees', ['legal_entity_id'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]

    # Drop indexes
    indexes = inspector.get_indexes('employees')
    existing_index_names = [idx['name'] for idx in indexes]
    for index_name in ['ix_employees_branch_id', 'ix_employees_legal_entity_id']:
        if index_name in existing_index_names:
            op.drop_index(index_name, table_name='employees')

    # Drop columns
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]
    for col_name in ['branch_id', 'legal_entity_id', 'state_code', 'pf_membership_active', 'is_eps_eligible', 'pf_higher_wage_opted', 'eps_higher_wage_opted', 'vpf_rate', 'is_pwd', 'esi_covered_at_period_start']:
        if col_name in existing_columns:
            op.drop_column('employees', col_name)