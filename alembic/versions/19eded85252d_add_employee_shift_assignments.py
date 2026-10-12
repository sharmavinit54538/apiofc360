"""add_employee_shift_assignments

Revision ID: 19eded85252d
Revises: 6edc3a852a7a
Create Date: 2026-10-12 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import text


revision: str = '19eded85252d'
down_revision: Union[str, None] = '6edc3a852a7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create employee_shift_assignments table
    op.create_table(
        'employee_shift_assignments',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', UUID(as_uuid=True), nullable=False),
        sa.Column('employee_id', UUID(as_uuid=True), nullable=False),
        sa.Column('shift_id', UUID(as_uuid=True), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('assigned_by', UUID(as_uuid=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_emp_shift_assign_employee', 'employee_shift_assignments', ['employee_id'])
    op.create_index('ix_emp_shift_assign_shift', 'employee_shift_assignments', ['shift_id'])
    op.create_index('ix_emp_shift_assign_company', 'employee_shift_assignments', ['company_id'])
    op.create_index('ix_emp_shift_assign_effective', 'employee_shift_assignments', ['employee_id', 'effective_from'],
                    postgresql_where=sa.text('effective_to IS NULL'))
    op.execute(text("""
        CREATE UNIQUE INDEX uq_emp_shift_assign_current
        ON employee_shift_assignments (employee_id)
        WHERE effective_to IS NULL
    """))

    # 2. Add shift_id to employees table
    op.add_column('employees', sa.Column('shift_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_employees_shift_id', 'employees', 'shifts', ['shift_id'], ['id'], ondelete='SET NULL')

    # 3. Backfill: create assignments from employee.shift string
    conn = op.get_bind()

    # Get employees with shift string
    employees = conn.execute(text("""
        SELECT e.id, e.company_id, e.shift, e.created_at
        FROM employees e
        WHERE e.shift IS NOT NULL AND e.shift != '' AND e.is_deleted = false
    """)).fetchall()

    for emp in employees:
        emp_id = str(emp.id)
        company_id = str(emp.company_id) if emp.company_id else None
        shift_name = emp.shift.strip()
        created_at = emp.created_at

        if not company_id:
            continue

        # Find matching shift (case-insensitive exact match on name)
        shift = conn.execute(text("""
            SELECT id FROM shifts
            WHERE company_id = :cid AND lower(trim(name)) = lower(trim(:name))
            AND deleted_at IS NULL
            ORDER BY is_default DESC, created_at ASC
            LIMIT 1
        """), {"cid": company_id, "name": shift_name}).scalar()

        if shift:
            shift_id = str(shift)
            # Create assignment
            conn.execute(text("""
                INSERT INTO employee_shift_assignments (id, company_id, employee_id, shift_id, effective_from, assigned_by, created_at)
                VALUES (gen_random_uuid(), :cid, :eid, :sid, :eff_from, :eid, :created_at)
            """), {
                "cid": company_id,
                "eid": emp_id,
                "sid": shift_id,
                "eff_from": created_at.date() if created_at else sa.func.current_date(),
            })
            # Update employee.shift_id
            conn.execute(text("UPDATE employees SET shift_id = :sid WHERE id = :eid"),
                         {"sid": shift_id, "eid": emp_id})
        else:
            # Log unmatched (in production, you'd log this)
            print(f"WARNING: No shift match for employee {emp_id} with shift name '{shift_name}'")


def downgrade() -> None:
    # Drop FK and column from employees
    op.drop_constraint('fk_employees_shift_id', 'employees', type_='foreignkey')
    op.drop_column('employees', 'shift_id')

    # Drop employee_shift_assignments table
    op.execute(text("DROP INDEX IF EXISTS uq_emp_shift_assign_current"))
    op.drop_index('ix_emp_shift_assign_effective', table_name='employee_shift_assignments')
    op.drop_index('ix_emp_shift_assign_company', table_name='employee_shift_assignments')
    op.drop_index('ix_emp_shift_assign_shift', table_name='employee_shift_assignments')
    op.drop_index('ix_emp_shift_assign_employee', table_name='employee_shift_assignments')
    op.drop_table('employee_shift_assignments')