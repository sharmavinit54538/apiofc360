"""convert_role_to_enum

Revision ID: f433d8a18647
Revises: e6f3490324d5
Create Date: 2026-07-02 14:35:07.620374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f433d8a18647'
down_revision: Union[str, None] = 'e6f3490324d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create native PostgreSQL ENUM if it doesn't exist
    bind = op.get_bind()
    has_type = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'user_role'")).scalar()
    if not has_type:
        op.execute("CREATE TYPE user_role AS ENUM ('ADMIN', 'MANAGER', 'EMPLOYEE')")

    # 2. Update existing data to uppercase to match the ENUM labels
    op.execute("UPDATE users SET role = UPPER(role) WHERE role IS NOT NULL AND role != UPPER(role)")

    # 3. Drop the VARCHAR default before type alteration to prevent datatype mismatch errors
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")

    # 4. Alter the column type to user_role
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::user_role")

    # 5. Set the new native enum default value (uppercase)
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'EMPLOYEE'::user_role")


def downgrade() -> None:
    # 1. Drop the default on the enum column
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")

    # 2. Alter column type back to VARCHAR(50) and convert values to lowercase
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50) USING LOWER(role::VARCHAR)")

    # 3. Restore default constraint (lowercase)
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'employee'")

    # 4. Drop the user_role ENUM type
    op.execute("DROP TYPE IF EXISTS user_role")

