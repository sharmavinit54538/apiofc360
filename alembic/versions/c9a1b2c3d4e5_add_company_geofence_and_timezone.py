"""add company geofence and timezone fields

Revision ID: c9a1b2c3d4e5
Revises: 3a4b5c6d7e8f
Create Date: 2026-09-18 07:45:00.000000

Non-destructive migration adding office geofence coordinates and timezone to companies table.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c9a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = '3a4b5c6d7e8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'companies' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('companies')]

        cols_to_add = [
            ('office_latitude', sa.Float(), None, True),
            ('office_longitude', sa.Float(), None, True),
            ('geofence_radius_meters', sa.Float(), None, True),
            ('timezone', sa.String(50), sa.text("'Asia/Kolkata'"), True),
        ]

        for col_name, col_type, default_val, is_nullable in cols_to_add:
            if col_name not in existing_cols:
                op.add_column(
                    'companies',
                    sa.Column(col_name, col_type, nullable=is_nullable, server_default=default_val)
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'companies' in inspector.get_table_names():
        existing_cols = [c['name'] for c in inspector.get_columns('companies')]
        cols_to_drop = ['office_latitude', 'office_longitude', 'geofence_radius_meters', 'timezone']
        for col_name in cols_to_drop:
            if col_name in existing_cols:
                op.drop_column('companies', col_name)
