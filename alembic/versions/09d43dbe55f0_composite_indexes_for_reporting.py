"""composite indexes for reporting

Revision ID: 09d43dbe55f0
Revises: e983ae2da073
Create Date: 2026-08-17 08:56:13.144362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '09d43dbe55f0'
down_revision: Union[str, None] = 'e983ae2da073'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_attendance_student_date", "attendance", ["student_id", "date"])
    op.create_index("ix_attendance_tenant_date", "attendance", ["tenant_id", "date"])
    op.create_index("ix_fees_tenant_status", "fees", ["tenant_id", "payment_status"])
    op.create_index("ix_students_tenant_class_section", "students", ["tenant_id", "class_name", "section"])
    op.create_index("ix_recognition_logs_student_time", "recognition_logs", ["student_id", "recognition_time"])
    op.create_index("ix_admissions_tenant_status", "admissions", ["tenant_id", "status"])
    # batch mode so this also works against SQLite (used for local/dev testing)
    with op.batch_alter_table("students") as batch_op:
        batch_op.create_unique_constraint("uq_students_tenant_admission_number", ["tenant_id", "admission_number"])
    with op.batch_alter_table("teachers") as batch_op:
        batch_op.create_unique_constraint("uq_teachers_tenant_employee_id", ["tenant_id", "employee_id"])
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_unique_constraint("uq_users_tenant_email", ["tenant_id", "email"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_tenant_email", type_="unique")
    with op.batch_alter_table("teachers") as batch_op:
        batch_op.drop_constraint("uq_teachers_tenant_employee_id", type_="unique")
    with op.batch_alter_table("students") as batch_op:
        batch_op.drop_constraint("uq_students_tenant_admission_number", type_="unique")
    op.drop_index("ix_admissions_tenant_status", table_name="admissions")
    op.drop_index("ix_recognition_logs_student_time", table_name="recognition_logs")
    op.drop_index("ix_students_tenant_class_section", table_name="students")
    op.drop_index("ix_fees_tenant_status", table_name="fees")
    op.drop_index("ix_attendance_tenant_date", table_name="attendance")
    op.drop_index("ix_attendance_student_date", table_name="attendance")
