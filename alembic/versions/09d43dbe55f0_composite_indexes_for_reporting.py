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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def _safe_index(name, table, cols):
        if table in tables:
            col_names = {c['name'] for c in inspector.get_columns(table)}
            if all(col in col_names for col in cols):
                existing_idxs = {idx['name'] for idx in inspector.get_indexes(table)}
                if name not in existing_idxs:
                    op.create_index(name, table, cols)

    _safe_index("ix_attendance_student_date", "attendance", ["student_id", "date"])
    _safe_index("ix_attendance_tenant_date", "attendance", ["tenant_id", "date"])
    _safe_index("ix_fees_tenant_status", "fees", ["tenant_id", "payment_status"])
    _safe_index("ix_students_tenant_class_section", "students", ["tenant_id", "class_name", "section"])
    _safe_index("ix_recognition_logs_student_time", "recognition_logs", ["student_id", "recognition_time"])
    _safe_index("ix_admissions_tenant_status", "admissions", ["tenant_id", "status"])

    if "students" in tables:
        cols = {c['name'] for c in inspector.get_columns("students")}
        if "tenant_id" in cols and "admission_number" in cols:
            with op.batch_alter_table("students") as batch_op:
                batch_op.create_unique_constraint("uq_students_tenant_admission_number", ["tenant_id", "admission_number"])
    if "teachers" in tables:
        cols = {c['name'] for c in inspector.get_columns("teachers")}
        if "tenant_id" in cols and "employee_id" in cols:
            with op.batch_alter_table("teachers") as batch_op:
                batch_op.create_unique_constraint("uq_teachers_tenant_employee_id", ["tenant_id", "employee_id"])
    if "users" in tables:
        cols = {c['name'] for c in inspector.get_columns("users")}
        if "tenant_id" in cols and "email" in cols:
            with op.batch_alter_table("users") as batch_op:
                batch_op.create_unique_constraint("uq_users_tenant_email", ["tenant_id", "email"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        with op.batch_alter_table("users") as batch_op:
            try:
                batch_op.drop_constraint("uq_users_tenant_email", type_="unique")
            except Exception:
                pass
    if "teachers" in tables:
        with op.batch_alter_table("teachers") as batch_op:
            try:
                batch_op.drop_constraint("uq_teachers_tenant_employee_id", type_="unique")
            except Exception:
                pass
    if "students" in tables:
        with op.batch_alter_table("students") as batch_op:
            try:
                batch_op.drop_constraint("uq_students_tenant_admission_number", type_="unique")
            except Exception:
                pass

    for idx, tbl in [
        ("ix_admissions_tenant_status", "admissions"),
        ("ix_recognition_logs_student_time", "recognition_logs"),
        ("ix_students_tenant_class_section", "students"),
        ("ix_fees_tenant_status", "fees"),
        ("ix_attendance_tenant_date", "attendance"),
        ("ix_attendance_student_date", "attendance"),
    ]:
        if tbl in tables:
            try:
                op.drop_index(idx, table_name=tbl)
            except Exception:
                pass
