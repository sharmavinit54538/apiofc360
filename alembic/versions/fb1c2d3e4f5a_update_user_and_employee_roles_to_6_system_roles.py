"""update user and employee roles to 6 fixed system roles

Revision ID: fb1c2d3e4f5a
Revises: fa0b9c8d7e6f
Create Date: 2026-08-13 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb1c2d3e4f5a'
down_revision: Union[str, None] = 'fa0b9c8d7e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    has_enum = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'user_role'")).scalar()

    # 1. Update data in employees table first if column is string
    op.execute("""
        UPDATE employees
        SET role = CASE
            WHEN LOWER(role) IN ('admin', 'super_admin', 'superadmin') THEN 'super_admin'
            WHEN LOWER(role) IN ('hr', 'hr_admin', 'hr_manager') THEN 'hr_admin'
            WHEN LOWER(role) = 'manager' THEN 'manager'
            WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'cmo', 'clo', 'ciso', 'cio', 'executive') THEN 'executive'
            WHEN LOWER(role) IN ('it_admin', 'itadmin') THEN 'it_admin'
            ELSE 'employee'
        END
        WHERE role IS NOT NULL;
    """)

    # 2. Update users table data if enum or string
    if has_enum:
        # Alter column to varchar temporarily to update values
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50) USING role::VARCHAR")

    op.execute("""
        UPDATE users
        SET role = CASE
            WHEN LOWER(role) IN ('admin', 'super_admin', 'superadmin') THEN 'super_admin'
            WHEN LOWER(role) IN ('hr', 'hr_admin', 'hr_manager') THEN 'hr_admin'
            WHEN LOWER(role) = 'manager' THEN 'manager'
            WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'cmo', 'clo', 'ciso', 'cio', 'executive') THEN 'executive'
            WHEN LOWER(role) IN ('it_admin', 'itadmin') THEN 'it_admin'
            ELSE 'employee'
        END
        WHERE role IS NOT NULL;
    """)

    if has_enum:
        # Recreate type user_role with new values
        op.execute("DROP TYPE IF EXISTS user_role CASCADE")
        op.execute("CREATE TYPE user_role AS ENUM ('super_admin', 'hr_admin', 'manager', 'employee', 'executive', 'it_admin')")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'::user_role")
    else:
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'")


def downgrade() -> None:
    pass
