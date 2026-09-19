"""standardize canonical role enum values across users, employees, and managers

Revision ID: ff1c2d3e4f5c
Revises: fe1c2d3e4f5b
Create Date: 2026-08-15 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff1c2d3e4f5c'
down_revision: Union[str, None] = 'fe1c2d3e4f5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    has_enum = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'user_role'")).scalar()

    # 1. Standardize legacy role strings in employees table
    op.execute("""
        UPDATE employees
        SET role = CASE
            WHEN LOWER(role) IN ('super_admin', 'superadmin', 'super_administrator') THEN 'super_admin'
            WHEN LOWER(role) IN ('admin', 'hr', 'hr_admin', 'hradmin', 'hr_manager', 'payroll_admin', 'finance') THEN 'hr_admin'
            WHEN LOWER(role) IN ('manager', 'lead', 'team_lead') THEN 'manager'
            WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'cmo', 'clo', 'ciso', 'cio', 'vp', 'director', 'executive') THEN 'executive'
            WHEN LOWER(role) IN ('it_admin', 'itadmin', 'it', 'tech_admin') THEN 'it_admin'
            WHEN LOWER(role) IN ('intern', 'internship', 'trainee') THEN 'intern'
            ELSE 'employee'
        END
        WHERE role IS NOT NULL;
    """)

    # 2. Standardize legacy role strings in managers table if managers table exists
    has_managers = bind.execute(sa.text("SELECT 1 FROM information_schema.tables WHERE table_name='managers'")).scalar()
    if has_managers:
        op.execute("""
            UPDATE managers
            SET role = CASE
                WHEN LOWER(role) IN ('super_admin', 'superadmin') THEN 'super_admin'
                WHEN LOWER(role) IN ('admin', 'hr', 'hr_admin', 'hradmin') THEN 'hr_admin'
                WHEN LOWER(role) IN ('ceo', 'cfo', 'cto', 'coo', 'executive') THEN 'executive'
                WHEN LOWER(role) IN ('it_admin', 'itadmin') THEN 'it_admin'
                ELSE 'manager'
            END
            WHERE role IS NOT NULL;
        """)

    # 3. Standardize users table data and ensure canonical enum values
    op.execute("DROP INDEX IF EXISTS uq_single_super_admin")
    if has_enum:
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50) USING role::VARCHAR")

    op.execute("""
        UPDATE users
        SET role = CASE
            WHEN LOWER(role::text) IN ('super_admin', 'superadmin', 'super_administrator') THEN 'super_admin'
            WHEN LOWER(role::text) IN ('admin', 'hr', 'hr_admin', 'hradmin', 'hr_manager', 'payroll_admin', 'finance') THEN 'hr_admin'
            WHEN LOWER(role::text) IN ('manager', 'lead', 'team_lead') THEN 'manager'
            WHEN LOWER(role::text) IN ('ceo', 'cfo', 'cto', 'coo', 'cmo', 'clo', 'ciso', 'cio', 'vp', 'director', 'executive') THEN 'executive'
            WHEN LOWER(role::text) IN ('it_admin', 'itadmin', 'it', 'tech_admin') THEN 'it_admin'
            WHEN LOWER(role::text) IN ('intern', 'internship', 'trainee') THEN 'intern'
            ELSE 'employee'
        END
        WHERE role IS NOT NULL;
    """)

    if has_enum:
        op.execute("DROP TYPE IF EXISTS user_role CASCADE")
        op.execute("CREATE TYPE user_role AS ENUM ('super_admin', 'hr_admin', 'manager', 'employee', 'executive', 'it_admin', 'intern')")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'::user_role")
    else:
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'")


def downgrade() -> None:
    pass
