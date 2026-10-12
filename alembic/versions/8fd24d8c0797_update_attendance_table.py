"""update_attendance_table

Revision ID: 8fd24d8c0797
Revises: 5fb62495dd8d
Create Date: 2026-10-12 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text


revision: str = '8fd24d8c0797'
down_revision: Union[str, None] = '5fb62495dd8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add new columns to attendances
    op.add_column('attendances', sa.Column('shift_source', sa.String(30), nullable=True))
    op.add_column('attendances', sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=True))
    op.add_column('attendances', sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=True))
    op.add_column('attendances', sa.Column('is_early_checkout', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('attendances', sa.Column('early_minutes', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('attendances', sa.Column('overtime_hours', sa.Float(), nullable=False, server_default=sa.text('0.0')))
    op.add_column('attendances', sa.Column('is_off_day_work', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('attendances', sa.Column('is_holiday_work', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('attendances', sa.Column('auto_closed', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('attendances', sa.Column('auto_closed_at', sa.DateTime(timezone=True), nullable=True))

    # 2. Clean orphan shift_id values and add FK
    # Set shift_id to NULL where no matching shift
    conn.execute(text("""
        UPDATE attendances a
        SET shift_id = NULL
        WHERE a.shift_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM shifts s WHERE s.id = a.shift_id AND s.deleted_at IS NULL)
    """))

    op.create_foreign_key('fk_attendances_shift_id', 'attendances', 'shifts', ['shift_id'], ['id'], ondelete='SET NULL')

    # 3. Handle duplicate open sessions (keep latest, auto-close others)
    # Find employees with multiple open sessions
    duplicate_open = conn.execute(text("""
        SELECT employee_id, COUNT(*) as cnt
        FROM attendances
        WHERE check_out_time IS NULL
        GROUP BY employee_id
        HAVING COUNT(*) > 1
    """)).fetchall()

    for row in duplicate_open:
        emp_id = str(row.employee_id)
        # Get all open sessions for this employee, ordered by check_in_time DESC
        sessions = conn.execute(text("""
            SELECT id, check_in_time, date
            FROM attendances
            WHERE employee_id = :eid AND check_out_time IS NULL
            ORDER BY check_in_time DESC
        """), {"eid": emp_id}).fetchall()

        if len(sessions) > 1:
            # Keep the latest (first), auto-close the rest
            latest_id = str(sessions[0].id)
            for session in sessions[1:]:
                session_id = str(session.id)
                conn.execute(text("""
                    UPDATE attendances
                    SET check_out_time = check_in_time,
                        working_hours = 0,
                        auto_closed = true,
                        auto_closed_at = now(),
                        notes = COALESCE(notes, '') || ' | Auto-closed by migration: duplicate open session'
                    WHERE id = :sid
                """), {"sid": session_id})

    # 4. Create partial unique index for open sessions (one per employee)
    op.execute(text("""
        CREATE UNIQUE INDEX uq_attendance_open_session
        ON attendances (employee_id)
        WHERE check_out_time IS NULL
    """))

    # 5. Create index for auto-close job
    op.create_index('ix_attendances_auto_close', 'attendances', ['check_out_time'],
                    postgresql_where=sa.text('check_out_time IS NULL'))


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_attendances_auto_close', table_name='attendances')
    op.execute(text("DROP INDEX IF EXISTS uq_attendance_open_session"))

    # Drop FK
    op.drop_constraint('fk_attendances_shift_id', 'attendances', type_='foreignkey')

    # Drop new columns
    op.drop_column('attendances', 'auto_closed_at')
    op.drop_column('attendances', 'auto_closed')
    op.drop_column('attendances', 'is_holiday_work')
    op.drop_column('attendances', 'is_off_day_work')
    op.drop_column('attendances', 'overtime_hours')
    op.drop_column('attendances', 'early_minutes')
    op.drop_column('attendances', 'is_early_checkout')
    op.drop_column('attendances', 'scheduled_end')
    op.drop_column('attendances', 'scheduled_start')
    op.drop_column('attendances', 'shift_source')