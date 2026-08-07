"""Add manager permission columns.

Revision ID: a1b2c3d4e5f6
Revises: f533d8a18648
Create Date: 2026-07-10 15:54:00

Adds 8 granular permission Boolean columns to the managers table:
  - can_approve_leave
  - can_approve_attendance
  - can_manage_employees
  - can_view_payroll
  - can_edit_departments
  - can_invite_users
  - can_manage_recruitment
  - can_manage_performance
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f533d8a18648"
branch_labels = None
depends_on = None

PERMISSION_COLUMNS = [
    ("can_approve_leave",      "Can approve leave"),
    ("can_approve_attendance",  "Can approve attendance"),
    ("can_manage_employees",    "Can manage employees"),
    ("can_view_payroll",        "Can view payroll"),
    ("can_edit_departments",    "Can edit departments"),
    ("can_invite_users",        "Can invite users"),
    ("can_manage_recruitment",  "Can manage recruitment"),
    ("can_manage_performance",  "Can manage performance"),
]


def upgrade() -> None:
    for col_name, comment in PERMISSION_COLUMNS:
        op.add_column(
            "managers",
            sa.Column(
                col_name,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                comment=comment,
            ),
        )


def downgrade() -> None:
    for col_name, _ in reversed(PERMISSION_COLUMNS):
        op.drop_column("managers", col_name)
