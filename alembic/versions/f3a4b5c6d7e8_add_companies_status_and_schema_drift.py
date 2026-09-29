"""add companies status and schema drift fixes

Revision ID: f3a4b5c6d7e8
Revises: e2a3b4c5d6e7
Create Date: 2026-09-29 15:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add status column to companies table (Task 1)
    op.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'PENDING'")
    op.execute("ALTER TABLE companies ALTER COLUMN status TYPE VARCHAR(50)")
    op.execute("UPDATE companies SET status = 'PENDING' WHERE status IS NULL")
    op.execute("ALTER TABLE companies ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE companies ALTER COLUMN status SET DEFAULT 'PENDING'")

    # 2. Add missing gratuity column to fnf_settlements (Task 2)
    op.execute("ALTER TABLE fnf_settlements ADD COLUMN IF NOT EXISTS gratuity NUMERIC(14, 2) NOT NULL DEFAULT 0.0")

    # 3. Add missing unique index on employee_invitations token (Task 2)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_employee_invitations_token ON employee_invitations (token)")

    # 4. Add missing foreign key for employee_investment_declarations.verified_by (Task 2)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_employee_investment_declarations_verified_by_users'
            ) THEN
                ALTER TABLE employee_investment_declarations
                ADD CONSTRAINT fk_employee_investment_declarations_verified_by_users
                FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)

    # 5. Add missing unique constraint on user_mfa.user_id (Task 2)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_mfa_user_id'
            ) THEN
                ALTER TABLE user_mfa
                ADD CONSTRAINT uq_user_mfa_user_id UNIQUE (user_id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # 1. Drop status column from companies table (Task 1)
    op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS status")

    # 2. Drop gratuity from fnf_settlements
    op.execute("ALTER TABLE fnf_settlements DROP COLUMN IF EXISTS gratuity")

    # 3. Drop employee_invitations token index
    op.execute("DROP INDEX IF EXISTS ix_employee_invitations_token")

    # 4. Drop employee_investment_declarations FK
    op.execute("ALTER TABLE employee_investment_declarations DROP CONSTRAINT IF EXISTS fk_employee_investment_declarations_verified_by_users")

    # 5. Drop user_mfa unique constraint
    op.execute("ALTER TABLE user_mfa DROP CONSTRAINT IF EXISTS uq_user_mfa_user_id")

