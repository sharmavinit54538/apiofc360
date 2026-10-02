"""dedupe and unique employee leave policies

Revision ID: d7e8f9a0b1c2
Revises: c8e9f0a1b2c3
Create Date: 2026-10-02 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # 1. Normalize legacy rows
        op.execute("""
            UPDATE employee_leave_policies
            SET leave_type = 'Sick Leave'
            WHERE UPPER(REPLACE(leave_type, ' ', '_')) IN ('SICK_LEAVE', 'SICK');
        """)
        op.execute("""
            UPDATE employee_leave_policies
            SET leave_type = 'Casual Leave'
            WHERE UPPER(REPLACE(leave_type, ' ', '_')) IN ('CASUAL_LEAVE', 'CASUAL');
        """)
        op.execute("""
            UPDATE employee_leave_policies
            SET leave_type = 'Vacation Leave'
            WHERE UPPER(REPLACE(leave_type, ' ', '_')) IN ('VACATION_LEAVE', 'VACATION', 'PRIVILEGE_LEAVE', 'PL');
        """)

        # 2. Dedupe employee_leave_policies: sum used_days, keep max total_days, delete extras
        op.execute("""
            CREATE TEMPORARY TABLE temp_policy_dedupe AS
            SELECT 
                (ARRAY_AGG(id ORDER BY created_at ASC, id ASC))[1] AS keeper_id,
                employee_id,
                leave_type,
                MAX(total_days) AS max_total,
                SUM(used_days) AS sum_used
            FROM employee_leave_policies
            GROUP BY employee_id, leave_type;

            UPDATE employee_leave_policies elp
            SET 
                total_days = t.max_total,
                used_days = t.sum_used
            FROM temp_policy_dedupe t
            WHERE elp.id = t.keeper_id;

            DELETE FROM employee_leave_policies
            WHERE id NOT IN (SELECT keeper_id FROM temp_policy_dedupe);

            DROP TABLE temp_policy_dedupe;
        """)

        # 3. Add UNIQUE constraint
        op.create_unique_constraint(
            'uq_employee_leave_policies_employee_leave_type',
            'employee_leave_policies',
            ['employee_id', 'leave_type']
        )
    else:
        # SQLite / Generic database dialect fallback for test suites
        op.execute("""
            UPDATE employee_leave_policies
            SET leave_type = 'Sick Leave'
            WHERE UPPER(REPLACE(leave_type, ' ', '_')) IN ('SICK_LEAVE', 'SICK');
        """)
        op.execute("""
            UPDATE employee_leave_policies
            SET leave_type = 'Casual Leave'
            WHERE UPPER(REPLACE(leave_type, ' ', '_')) IN ('CASUAL_LEAVE', 'CASUAL');
        """)
        op.execute("""
            UPDATE employee_leave_policies
            SET leave_type = 'Vacation Leave'
            WHERE UPPER(REPLACE(leave_type, ' ', '_')) IN ('VACATION_LEAVE', 'VACATION', 'PRIVILEGE_LEAVE', 'PL');
        """)

        conn = bind
        rows = conn.execute(sa.text("SELECT id, employee_id, leave_type, total_days, used_days FROM employee_leave_policies")).fetchall()
        groups = {}
        for r in rows:
            key = (str(r[1]), str(r[2]))
            groups.setdefault(key, []).append(r)

        for key, items in groups.items():
            if len(items) > 1:
                keeper = items[0]
                max_total = max(float(x[3]) for x in items)
                sum_used = sum(float(x[4]) for x in items)
                conn.execute(
                    sa.text("UPDATE employee_leave_policies SET total_days = :tot, used_days = :used WHERE id = :id"),
                    {"tot": max_total, "used": sum_used, "id": keeper[0]}
                )
                for extra in items[1:]:
                    conn.execute(
                        sa.text("DELETE FROM employee_leave_policies WHERE id = :id"),
                        {"id": extra[0]}
                    )

        with op.batch_alter_table('employee_leave_policies') as batch_op:
            batch_op.create_unique_constraint(
                'uq_employee_leave_policies_employee_leave_type',
                ['employee_id', 'leave_type']
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.drop_constraint('uq_employee_leave_policies_employee_leave_type', 'employee_leave_policies', type_='unique')
    else:
        with op.batch_alter_table('employee_leave_policies') as batch_op:
            batch_op.drop_constraint('uq_employee_leave_policies_employee_leave_type', type_='unique')
