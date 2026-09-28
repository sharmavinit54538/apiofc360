"""add face attendance biometric columns

Revision ID: fe2c3d4e5f6b
Revises: 09d43dbe55f0, c9a1b2c3d4e5, ff3c4d5e6f7a
Create Date: 2026-09-18 18:00:00.000000

Non-destructive idempotent migration adding biometric face recognition columns to:
- employees (face_embedding, is_face_enrolled, face_enrolled_at)
- users (is_face_enrolled, face_enrolled_at)
- attendances (captured_face_url, status, punch_type, verified, punch_verified_by, notes)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'fe2c3d4e5f6b'
down_revision: Union[str, Sequence[str], None] = ('09d43dbe55f0', 'c9a1b2c3d4e5', 'ff3c4d5e6f7a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Update employees table
    if 'employees' in existing_tables:
        existing_cols = [c['name'] for c in inspector.get_columns('employees')]
        
        if 'face_embedding' not in existing_cols:
            op.add_column(
                'employees',
                sa.Column('face_embedding', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=True)
            )
        if 'is_face_enrolled' not in existing_cols:
            op.add_column(
                'employees',
                sa.Column('is_face_enrolled', sa.Boolean(), nullable=False, server_default=sa.text('false'))
            )
        if 'face_enrolled_at' not in existing_cols:
            op.add_column(
                'employees',
                sa.Column('face_enrolled_at', sa.DateTime(timezone=True), nullable=True)
            )

    # 2. Update users table
    if 'users' in existing_tables:
        existing_cols = [c['name'] for c in inspector.get_columns('users')]

        if 'is_face_enrolled' not in existing_cols:
            op.add_column(
                'users',
                sa.Column('is_face_enrolled', sa.Boolean(), nullable=False, server_default=sa.text('false'))
            )
        if 'face_enrolled_at' not in existing_cols:
            op.add_column(
                'users',
                sa.Column('face_enrolled_at', sa.DateTime(timezone=True), nullable=True)
            )

    # 3. Update attendances table
    if 'attendances' in existing_tables:
        existing_cols = [c['name'] for c in inspector.get_columns('attendances')]

        if 'captured_face_url' not in existing_cols:
            op.add_column(
                'attendances',
                sa.Column('captured_face_url', sa.String(length=500), nullable=True)
            )
        if 'status' not in existing_cols:
            op.add_column(
                'attendances',
                sa.Column('status', sa.String(length=20), nullable=False, server_default=sa.text("'Present'"))
            )
        if 'punch_type' not in existing_cols:
            op.add_column(
                'attendances',
                sa.Column('punch_type', sa.String(length=10), nullable=False, server_default=sa.text("'IN'"))
            )
        if 'verified' not in existing_cols:
            op.add_column(
                'attendances',
                sa.Column('verified', sa.Boolean(), nullable=False, server_default=sa.text('true'))
            )
        if 'punch_verified_by' not in existing_cols:
            op.add_column(
                'attendances',
                sa.Column('punch_verified_by', sa.String(length=20), nullable=True, server_default=sa.text("'FACE'"))
            )
        if 'notes' not in existing_cols:
            op.add_column(
                'attendances',
                sa.Column('notes', sa.String(length=500), nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'attendances' in existing_tables:
        existing_cols = [c['name'] for c in inspector.get_columns('attendances')]
        for col in ['notes', 'punch_verified_by', 'verified', 'punch_type', 'status', 'captured_face_url']:
            if col in existing_cols:
                op.drop_column('attendances', col)

    if 'users' in existing_tables:
        existing_cols = [c['name'] for c in inspector.get_columns('users')]
        for col in ['face_enrolled_at', 'is_face_enrolled']:
            if col in existing_cols:
                op.drop_column('users', col)

    if 'employees' in existing_tables:
        existing_cols = [c['name'] for c in inspector.get_columns('employees')]
        for col in ['face_enrolled_at', 'is_face_enrolled', 'face_embedding']:
            if col in existing_cols:
                op.drop_column('employees', col)
