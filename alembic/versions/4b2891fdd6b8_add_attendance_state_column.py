"""add_attendance_state_column

Revision ID: 4b2891fdd6b8
Revises: 36bffd8d9cb4
Create Date: 2026-11-16 07:48:33.148155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4b2891fdd6b8'
down_revision: Union[str, None] = '36bffd8d9cb4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add attendance_state column to attendances table
    op.add_column('attendances', sa.Column('attendance_state', sa.String(length=30), nullable=False, server_default='CHECKED_IN'))
    
    # Add indexes
    op.create_index('ix_attendances_state', 'attendances', ['attendance_state'], unique=False)
    op.create_index('ix_attendances_check_out_time', 'attendances', ['check_out_time'], unique=False)
    
    # Add partial unique index for open sessions (one active session per employee)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_open_session 
        ON attendances (employee_id) 
        WHERE check_out_time IS NULL
    """)
    
    # Add check constraint for valid attendance states
    op.execute("""
        ALTER TABLE attendances 
        ADD CONSTRAINT ck_attendance_state_valid 
        CHECK (attendance_state IN ('CHECKED_IN', 'ON_BREAK', 'CHECKED_OUT', 'AUTO_CHECKED_OUT', 'CORRECTION_PENDING', 'CORRECTED'))
    """)


def downgrade() -> None:
    # Drop check constraint
    op.execute("ALTER TABLE attendances DROP CONSTRAINT IF EXISTS ck_attendance_state_valid")
    
    # Drop partial unique index
    op.execute("DROP INDEX IF EXISTS uq_attendance_open_session")
    
    # Drop indexes
    op.drop_index('ix_attendances_check_out_time', table_name='attendances')
    op.drop_index('ix_attendances_state', table_name='attendances')
    
    # Drop column
    op.drop_column('attendances', 'attendance_state')