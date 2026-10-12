"""add_shifts_table_and_columns

Revision ID: 6edc3a852a7a
Revises: f2g3h4i5j6k7
Create Date: 2026-10-12 07:40:17.279171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = '6edc3a852a7a'
down_revision: Union[str, None] = 'f2g3h4i5j6k7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new columns to shifts table (nullable first for data migration)
    op.add_column('shifts', sa.Column('code', sa.String(20), nullable=True))
    op.add_column('shifts', sa.Column('start_time_new', sa.Time(), nullable=True))
    op.add_column('shifts', sa.Column('end_time_new', sa.Time(), nullable=True))
    op.add_column('shifts', sa.Column('is_overnight', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('shifts', sa.Column('duration_minutes', sa.Integer(), nullable=False, server_default=sa.text('0')))
    op.add_column('shifts', sa.Column('grace_period_minutes', sa.Integer(), nullable=False, server_default=sa.text('15')))
    op.add_column('shifts', sa.Column('break_duration_minutes', sa.Integer(), nullable=False, server_default=sa.text('60')))
    op.add_column('shifts', sa.Column('work_hours', sa.Numeric(4, 2), nullable=False, server_default=sa.text('0.0')))
    op.add_column('shifts', sa.Column('is_night_shift', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('shifts', sa.Column('night_premium_percent', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')))
    op.add_column('shifts', sa.Column('working_days', sa.JSON(), nullable=False, server_default=sa.text("'[\"Mon\", \"Tue\", \"Wed\", \"Thu\", \"Fri\"]'::json")))
    op.add_column('shifts', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('shifts', sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('shifts', sa.Column('color', sa.String(9), nullable=True))
    op.add_column('shifts', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('shifts', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.text('now()')))
    op.add_column('shifts', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    # 2. Data migration: convert existing shifts using op.execute for better parameter handling
    conn = op.get_bind()

    # Get all existing shifts
    result = conn.execute(sa.text("""
        SELECT id, company_id, name, start_time, end_time
        FROM shifts
        WHERE deleted_at IS NULL
    """))
    shifts = result.fetchall()

    # Get company settings for default_shift
    company_defaults = {}
    for row in conn.execute(sa.text("SELECT company_id, default_shift FROM company_settings")).fetchall():
        company_defaults[str(row.company_id)] = row.default_shift

    for shift in shifts:
        shift_id = str(shift.id)
        company_id = str(shift.company_id)
        name = shift.name
        start_str = shift.start_time or "09:00"
        end_str = shift.end_time or "18:00"

        # Parse times
        def parse_time_simple(t_str: str) -> str:
            t_str = t_str.strip().upper()
            if ':' in t_str:
                parts = t_str.split(':')
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                if 'AM' in t_str or 'PM' in t_str:
                    period = 'AM' if 'AM' in t_str else 'PM'
                    if period == 'AM':
                        h = 0 if h == 12 else h
                    else:
                        h = 12 if h == 12 else h + 12
                return f"{h:02d}:{m:02d}:00"
            return "09:00:00"

        start_time = parse_time_simple(start_str)
        end_time = parse_time_simple(end_str)

        # Determine is_overnight
        start_h = int(start_time.split(':')[0])
        end_h = int(end_time.split(':')[0])
        is_overnight = end_h < start_h

        # Calculate duration_minutes
        if is_overnight:
            duration = (24 - start_h) * 60 + end_h * 60
        else:
            duration = (end_h - start_h) * 60
        if duration <= 0:
            duration = 540

        # Calculate work_hours (duration - break)
        break_min = 60
        work_hrs = round(max(0, duration - break_min) / 60.0, 2)

        # Generate code from name
        base_code = ''.join(c for c in name.upper() if c.isalnum() or c in '_-')[:20]
        if not base_code:
            base_code = 'SHIFT'
        code = base_code
        suffix = 1
        while conn.execute(
            sa.text("SELECT 1 FROM shifts WHERE company_id = :cid AND code = :code AND id != :sid"),
            {"cid": company_id, "code": code, "sid": shift_id}
        ).scalar():
            code = f"{base_code}{suffix}"
            suffix += 1

        # Check if this is the default shift
        is_default = False
        default_name = company_defaults.get(company_id, "").strip().lower()
        if default_name and default_name == name.strip().lower():
            is_default = True

        # Use op.execute with inline values to avoid parameter issues
        op.execute(f"""
            UPDATE shifts SET
                code = '{code}',
                start_time_new = '{start_time}'::time,
                end_time_new = '{end_time}'::time,
                is_overnight = {str(is_overnight).lower()},
                duration_minutes = {duration},
                grace_period_minutes = 15,
                break_duration_minutes = 60,
                work_hours = {work_hrs},
                is_night_shift = false,
                night_premium_percent = 0,
                working_days = '["Mon", "Tue", "Wed", "Thu", "Fri"]'::json,
                is_active = true,
                is_default = {str(is_default).lower()},
                color = '#6366F1',
                description = '',
                updated_at = now()
            WHERE id = '{shift_id}'
        """)

    # 3. Ensure every company has a default shift
    companies_without_default = conn.execute(sa.text("""
        SELECT DISTINCT c.id FROM companies c
        WHERE NOT EXISTS (
            SELECT 1 FROM shifts s WHERE s.company_id = c.id AND s.is_default = true AND s.deleted_at IS NULL
        )
    """)).fetchall()

    for company in companies_without_default:
        company_id = str(company.id)
        op.execute(f"""
            INSERT INTO shifts (id, company_id, code, name, start_time, end_time, start_time_new, end_time_new,
                              is_overnight, duration_minutes, grace_period_minutes,
                              break_duration_minutes, work_hours, is_night_shift,
                              night_premium_percent, working_days, is_active, is_default,
                              color, description, created_at, updated_at)
            VALUES (gen_random_uuid(), '{company_id}', 'GEN', 'General Shift', '09:00', '18:00', '09:00:00'::time, '18:00:00'::time,
                    false, 540, 15, 60, 8.00, false, 0,
                    '["Mon", "Tue", "Wed", "Thu", "Fri"]'::json, true, true,
                    '#6366F1', '', now(), now())
        """)

        op.execute(f"UPDATE company_settings SET default_shift = 'General Shift' WHERE company_id = '{company_id}'")

    # 4. Make columns NOT NULL and drop old columns
    op.alter_column('shifts', 'code', nullable=False)
    op.alter_column('shifts', 'start_time_new', nullable=False)
    op.alter_column('shifts', 'end_time_new', nullable=False)

    op.drop_column('shifts', 'start_time')
    op.drop_column('shifts', 'end_time')
    op.alter_column('shifts', 'start_time_new', new_column_name='start_time')
    op.alter_column('shifts', 'end_time_new', new_column_name='end_time')

    # 5. Add CHECK constraint
    op.create_check_constraint('ck_shifts_start_ne_end', 'shifts', 'start_time <> end_time')
    op.create_check_constraint('ck_shifts_grace_period_range', 'shifts', 'grace_period_minutes >= 0 AND grace_period_minutes <= 120')
    op.create_check_constraint('ck_shifts_break_range', 'shifts', 'break_duration_minutes >= 0 AND break_duration_minutes <= 180')
    op.create_check_constraint('ck_shifts_night_premium_range', 'shifts', 'night_premium_percent >= 0 AND night_premium_percent <= 100')

    # 6. Create partial unique indexes (excluding soft-deleted)
    op.execute("""
        CREATE UNIQUE INDEX uq_shifts_company_code_active
        ON shifts (company_id, code)
        WHERE deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_shifts_company_name_active
        ON shifts (company_id, name)
        WHERE deleted_at IS NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_shifts_company_default_active
        ON shifts (company_id)
        WHERE is_default = true AND deleted_at IS NULL
    """)

    op.create_index('ix_shifts_company_id', 'shifts', ['company_id'])
    op.create_index('ix_shifts_is_active', 'shifts', ['is_active'])
    op.create_index('ix_shifts_deleted_at', 'shifts', ['deleted_at'])


def downgrade() -> None:
    op.drop_index('ix_shifts_deleted_at', table_name='shifts')
    op.drop_index('ix_shifts_is_active', table_name='shifts')
    op.drop_index('ix_shifts_company_id', table_name='shifts')
    op.execute("DROP INDEX IF EXISTS uq_shifts_company_default_active")
    op.execute("DROP INDEX IF EXISTS uq_shifts_company_name_active")
    op.execute("DROP INDEX IF EXISTS uq_shifts_company_code_active")

    op.drop_constraint('ck_shifts_night_premium_range', 'shifts', type_='check')
    op.drop_constraint('ck_shifts_break_range', 'shifts', type_='check')
    op.drop_constraint('ck_shifts_grace_period_range', 'shifts', type_='check')
    op.drop_constraint('ck_shifts_start_ne_end', 'shifts', type_='check')

    op.add_column('shifts', sa.Column('start_time_old', sa.String(20), nullable=True))
    op.add_column('shifts', sa.Column('end_time_old', sa.String(20), nullable=True))

    conn = op.get_bind()
    shifts = conn.execute(sa.text("SELECT id, start_time, end_time FROM shifts WHERE deleted_at IS NULL")).fetchall()
    for shift in shifts:
        start_str = shift.start_time.strftime('%H:%M') if shift.start_time else '09:00'
        end_str = shift.end_time.strftime('%H:%M') if shift.end_time else '18:00'
        conn.execute(
            sa.text("UPDATE shifts SET start_time_old = :s, end_time_old = :e WHERE id = :id"),
            {"s": start_str, "e": end_str, "id": str(shift.id)}
        )

    op.drop_column('shifts', 'start_time')
    op.drop_column('shifts', 'end_time')
    op.alter_column('shifts', 'start_time_old', new_column_name='start_time')
    op.alter_column('shifts', 'end_time_old', new_column_name='end_time')

    op.drop_column('shifts', 'code')
    op.drop_column('shifts', 'is_overnight')
    op.drop_column('shifts', 'duration_minutes')
    op.drop_column('shifts', 'grace_period_minutes')
    op.drop_column('shifts', 'break_duration_minutes')
    op.drop_column('shifts', 'work_hours')
    op.drop_column('shifts', 'is_night_shift')
    op.drop_column('shifts', 'night_premium_percent')
    op.drop_column('shifts', 'working_days')
    op.drop_column('shifts', 'is_active')
    op.drop_column('shifts', 'is_default')
    op.drop_column('shifts', 'color')
    op.drop_column('shifts', 'description')
    op.drop_column('shifts', 'updated_at')
    op.drop_column('shifts', 'deleted_at')