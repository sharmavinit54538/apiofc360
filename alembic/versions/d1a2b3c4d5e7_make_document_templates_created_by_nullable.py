"""Make document_templates.created_by nullable and set ondelete SET NULL.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-17 07:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'document_templates' in insp.get_table_names():
        # 1. Alter created_by column to nullable
        cols = {c['name']: c for c in insp.get_columns('document_templates')}
        if 'created_by' in cols and not cols['created_by'].get('nullable', True):
            op.alter_column(
                'document_templates',
                'created_by',
                existing_type=postgresql.UUID(as_uuid=True),
                nullable=True,
            )

        # 2. Update foreign key constraint with ondelete SET NULL
        existing_fks = {fk['name']: fk for fk in insp.get_foreign_keys('document_templates')}
        if 'fk_document_templates_created_by_users' in existing_fks:
            op.drop_constraint('fk_document_templates_created_by_users', 'document_templates', type_='foreignkey')
        op.create_foreign_key(
            'fk_document_templates_created_by_users',
            'document_templates',
            'users',
            ['created_by'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'document_templates' in insp.get_table_names():
        existing_fks = {fk['name']: fk for fk in insp.get_foreign_keys('document_templates')}
        if 'fk_document_templates_created_by_users' in existing_fks:
            op.drop_constraint('fk_document_templates_created_by_users', 'document_templates', type_='foreignkey')
        op.create_foreign_key(
            'fk_document_templates_created_by_users',
            'document_templates',
            'users',
            ['created_by'],
            ['id'],
            ondelete='CASCADE',
        )
        op.alter_column(
            'document_templates',
            'created_by',
            existing_type=postgresql.UUID(as_uuid=True),
            nullable=False,
        )
