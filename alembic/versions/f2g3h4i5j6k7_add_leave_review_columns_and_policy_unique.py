"""Add reviewed_by_id, reviewed_at to leave_requests and unique constraint on employee_leave_policies

Revision ID: f2g3h4i5j6k7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2g3h4i5j6k7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Add reviewed_by_id and reviewed_at columns to leave_requests
    with op.batch_alter_table('leave_requests') as batch_op:
        batch_op.add_column(sa.Column('reviewed_by_id', sa.UUID(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))

    # Add foreign key for reviewed_by_id
    if dialect == "postgresql":
        op.create_foreign_key(
            'fk_leave_requests_reviewed_by_id_users',
            'leave_requests', 'users',
            ['reviewed_by_id'], ['id'],
            ondelete='SET NULL'
        )
    else:
        # SQLite doesn't support adding FK in batch mode easily, use raw SQL
        pass

    # 2. Handle employee_leave_policies unique constraint on (employee_id, leave_type, effective_from)
    # First check if the old unique constraint exists and drop it
    if dialect == "postgresql":
        # Check for existing unique constraint on (employee_id, leave_type)
        result = bind.execute(sa.text("""
            SELECT conname FROM pg_constraint 
            WHERE conrelid = 'employee_leave_policies'::regclass 
            AND contype = 'u'
            AND conname = 'uq_employee_leave_policies_employee_leave_type'
        """))
        if result.fetchone():
            op.drop_constraint(
                'uq_employee_leave_policies_employee_leave_type',
                'employee_leave_policies',
                type_='unique'
            )

        # Check for duplicates on (employee_id, leave_type, effective_from) before adding constraint
        # Use a CTE to find duplicates
        duplicates = bind.execute(sa.text("""
            SELECT employee_id, leave_type, effective_from, COUNT(*) as cnt
            FROM employee_leave_policies
            GROUP BY employee_id, leave_type, effective_from
            HAVING COUNT(*) > 1
        """)).fetchall()

        if duplicates:
            # For each duplicate group, keep the one with the latest created_at, sum used_days, max total_days
            for dup in duplicates:
                emp_id, leave_type, eff_from, cnt = dup
                # Get all duplicate rows ordered by created_at desc
                rows = bind.execute(sa.text("""
                    SELECT id, total_days, used_days, created_at
                    FROM employee_leave_policies
                    WHERE employee_id = :emp_id AND leave_type = :ltype AND (effective_from = :eff_from OR (effective_from IS NULL AND :eff_from IS NULL))
                    ORDER BY created_at DESC
                """), {"emp_id": emp_id, "ltype": leave_type, "eff_from": eff_from}).fetchall()

                if len(rows) > 1:
                    keeper = rows[0]
                    max_total = max(float(r[1]) for r in rows)
                    sum_used = sum(float(r[2]) for r in rows)
                    
                    # Update keeper
                    bind.execute(sa.text("""
                        UPDATE employee_leave_policies 
                        SET total_days = :tot, used_days = :used 
                        WHERE id = :kid
                    """), {"tot": max_total, "used": sum_used, "kid": keeper[0]})
                    
                    # Delete others
                    for extra in rows[1:]:
                        bind.execute(sa.text("DELETE FROM employee_leave_policies WHERE id = :id"), {"id": extra[0]})

        # Add new unique constraint
        op.create_unique_constraint(
            'uq_employee_leave_policies_emp_type_eff',
            'employee_leave_policies',
            ['employee_id', 'leave_type', 'effective_from']
        )
    else:
        # SQLite fallback
        with op.batch_alter_table('employee_leave_policies') as batch_op:
            # Drop old constraint if exists
            try:
                batch_op.drop_constraint('uq_employee_leave_policies_employee_leave_type', type_='unique')
            except Exception:
                pass
            
            # Check duplicates
            conn = bind
            rows = conn.execute(sa.text("SELECT id, employee_id, leave_type, effective_from, total_days, used_days FROM employee_leave_policies")).fetchall()
            groups = {}
            for r in rows:
                key = (str(r[1]), str(r[2]), str(r[3]) if r[3] else "NULL")
                groups.setdefault(key, []).append(r)

            for key, items in groups.items():
                if len(items) > 1:
                    keeper = items[0]
                    max_total = max(float(x[4]) for x in items)
                    sum_used = sum(float(x[5]) for x in items)
                    conn.execute(
                        sa.text("UPDATE employee_leave_policies SET total_days = :tot, used_days = :used WHERE id = :id"),
                        {"tot": max_total, "used": sum_used, "id": keeper[0]}
                    )
                    for extra in items[1:]:
                        conn.execute(
                            sa.text("DELETE FROM employee_leave_policies WHERE id = :id"),
                            {"id": extra[0]}
                        )
            
            batch_op.create_unique_constraint(
                'uq_employee_leave_policies_emp_type_eff',
                ['employee_id', 'leave_type', 'effective_from']
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop the new unique constraint
    if dialect == "postgresql":
        op.drop_constraint('uq_employee_leave_policies_emp_type_eff', 'employee_leave_policies', type_='unique')
        
        # Recreate the old unique constraint
        op.create_unique_constraint(
            'uq_employee_leave_policies_employee_leave_type',
            'employee_leave_policies',
            ['employee_id', 'leave_type']
        )
        
        # Drop foreign key and columns
        op.drop_constraint('fk_leave_requests_reviewed_by_id_users', 'leave_requests', type_='foreignkey')
        with op.batch_alter_table('leave_requests') as batch_op:
            batch_op.drop_column('reviewed_at')
            batch_op.drop_column('reviewed_by_id')
    else:
        with op.batch_alter_table('employee_leave_policies') as batch_op:
            batch_op.drop_constraint('uq_employee_leave_policies_emp_type_eff', type_='unique')
            batch_op.create_unique_constraint(
                'uq_employee_leave_policies_employee_leave_type',
                ['employee_id', 'leave_type']
            )
        
        with op.batch_alter_table('leave_requests') as batch_op:
            batch_op.drop_column('reviewed_at')
            batch_op.drop_column('reviewed_by_id')