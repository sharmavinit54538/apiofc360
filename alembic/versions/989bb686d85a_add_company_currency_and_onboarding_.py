"""add_company_currency_and_onboarding_safety

Revision ID: 989bb686d85a
Revises: 383b3a18b96d
Create Date: 2026-09-30 09:09:00.575510

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '989bb686d85a'
down_revision: Union[str, None] = '383b3a18b96d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # 1. Create employee_invitations if missing (matches app/models/employee_invitation.py)
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
        inv_cols = {c["name"] for c in insp.get_columns("employee_invitations")}
        if "token_hash" not in inv_cols:
            op.add_column("employee_invitations", sa.Column("token_hash", sa.String(128), nullable=True))
        if "delivery_status" not in inv_cols:
            op.add_column("employee_invitations", sa.Column("delivery_status", sa.String(30), server_default=sa.text("'QUEUED'"), nullable=False))
        if "delivery_error" not in inv_cols:
            op.add_column("employee_invitations", sa.Column("delivery_error", sa.String(255), nullable=True))
        if "last_sent_at" not in inv_cols:
            op.add_column("employee_invitations", sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Add missing columns to companies idempotently
    if "companies" in tables:
        comp_cols = {c["name"] for c in insp.get_columns("companies")}
        if "currency" not in comp_cols:
            op.add_column("companies", sa.Column("currency", sa.String(10), server_default=sa.text("'INR'"), nullable=True))
        if "timezone" not in comp_cols:
            op.add_column("companies", sa.Column("timezone", sa.String(50), server_default=sa.text("'Asia/Kolkata'"), nullable=True))
        if "status" not in comp_cols:
            op.add_column("companies", sa.Column("status", sa.String(50), server_default=sa.text("'PENDING'"), nullable=False))
        if "hr_settings" not in comp_cols:
            op.add_column("companies", sa.Column("hr_settings", sa.JSON(), nullable=True))
        if "office_latitude" not in comp_cols:
            op.add_column("companies", sa.Column("office_latitude", sa.Float(), nullable=True))
        if "office_longitude" not in comp_cols:
            op.add_column("companies", sa.Column("office_longitude", sa.Float(), nullable=True))
        if "geofence_radius_meters" not in comp_cols:
            op.add_column("companies", sa.Column("geofence_radius_meters", sa.Float(), server_default=sa.text("200.0"), nullable=True))

    # 3. Add missing columns to onboarding_progress idempotently
    if "onboarding_progress" in tables:
        prog_cols = {c["name"] for c in insp.get_columns("onboarding_progress")}
        cols_to_add = [
            ("company_completed", sa.Boolean(), sa.text("false"), False),
            ("admin_completed", sa.Boolean(), sa.text("false"), False),
            ("hr_completed", sa.Boolean(), sa.text("false"), False),
            ("departments_completed", sa.Boolean(), sa.text("false"), False),
            ("designations_completed", sa.Boolean(), sa.text("false"), False),
            ("employees_invited", sa.Boolean(), sa.text("false"), False),
            ("onboarding_completed", sa.Boolean(), sa.text("false"), False),
            ("data", sa.JSON(), None, True),
        ]
        for col_name, col_type, s_default, is_nullable in cols_to_add:
            if col_name not in prog_cols:
                op.add_column(
                    "onboarding_progress",
                    sa.Column(col_name, col_type, server_default=s_default, nullable=is_nullable),
                )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "companies" in tables:
        comp_cols = {c["name"] for c in insp.get_columns("companies")}
        if "currency" in comp_cols:
            op.drop_column("companies", "currency")
