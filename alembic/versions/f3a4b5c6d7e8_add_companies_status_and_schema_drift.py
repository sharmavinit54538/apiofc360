"""add companies status and schema drift fixes

Revision ID: f3a4b5c6d7e8
Revises: e2a3b4c5d6e7
Create Date: 2026-09-29 15:45:00.000000

"""
import uuid
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Add status column to companies table (Task 1)
    if "companies" in tables:
        comp_cols = {c["name"] for c in inspector.get_columns("companies")}
        if "status" not in comp_cols:
            op.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'PENDING'")
        op.execute("ALTER TABLE companies ALTER COLUMN status TYPE VARCHAR(50)")
        op.execute("UPDATE companies SET status = 'PENDING' WHERE status IS NULL")
        op.execute("ALTER TABLE companies ALTER COLUMN status SET NOT NULL")
        op.execute("ALTER TABLE companies ALTER COLUMN status SET DEFAULT 'PENDING'")

    # 2. Add missing gratuity column to fnf_settlements (Task 2)
    if "fnf_settlements" in tables:
        fnf_cols = {c["name"] for c in inspector.get_columns("fnf_settlements")}
        if "gratuity" not in fnf_cols:
            op.execute("ALTER TABLE fnf_settlements ADD COLUMN IF NOT EXISTS gratuity NUMERIC(14, 2) NOT NULL DEFAULT 0.0")

    # 3. Create employee_invitations table if not exists, and create indexes (Task 2)
    if "employee_invitations" not in tables:
        op.create_table(
            "employee_invitations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("employee_name", sa.String(255), nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("department", sa.String(100), nullable=True),
            sa.Column("designation", sa.String(100), nullable=True),
            sa.Column("token", sa.String(128), unique=True, nullable=False),
            sa.Column("token_hash", sa.String(128), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'PENDING'")),
            sa.Column("delivery_status", sa.String(30), nullable=False, server_default=sa.text("'QUEUED'")),
            sa.Column("delivery_error", sa.String(255), nullable=True),
            sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_employee_invitations_company_id", "employee_invitations", ["company_id"])
        op.create_index("ix_employee_invitations_email", "employee_invitations", ["email"])
        op.create_index("ix_employee_invitations_status", "employee_invitations", ["status"])
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_employee_invitations_token ON employee_invitations (token)")
    else:
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_employee_invitations_token ON employee_invitations (token)")

    # 4. Add missing foreign key for employee_investment_declarations.verified_by (Task 2)
    if "employee_investment_declarations" in tables:
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
    if "user_mfa" in tables:
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Drop status column from companies table (Task 1)
    if "companies" in tables:
        op.execute("ALTER TABLE companies DROP COLUMN IF EXISTS status")

    # 2. Drop gratuity from fnf_settlements
    if "fnf_settlements" in tables:
        op.execute("ALTER TABLE fnf_settlements DROP COLUMN IF EXISTS gratuity")

    # 3. Drop employee_invitations table
    if "employee_invitations" in tables:
        op.drop_table("employee_invitations")

    # 4. Drop employee_investment_declarations FK
    if "employee_investment_declarations" in tables:
        op.execute("ALTER TABLE employee_investment_declarations DROP CONSTRAINT IF EXISTS fk_employee_investment_declarations_verified_by_users")

    # 5. Drop user_mfa unique constraint
    if "user_mfa" in tables:
        op.execute("ALTER TABLE user_mfa DROP CONSTRAINT IF EXISTS uq_user_mfa_user_id")

