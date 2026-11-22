"""Enforce tenant isolation on SecurityPolicy, IPWhitelist, and SecurityRole.

- Add company_id NOT NULL constraint with backfill for existing records
- Add indexes for tenant-scoped queries
- SecurityPolicy: ensure single policy per company (unique constraint)
- SecurityRole: unique role_code per company
- IPWhitelist: index on company_id for fast tenant lookups

Revision ID: 921a_security_policy_tenant_isolation
Revises: 920a_digilocker_evidence
Create Date: 2026-11-22
"""

from __future__ import annotations

import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "921a_security_policy_tenant_isolation"
down_revision = "920a_digilocker_evidence"
branch_labels = None
depends_on = None


def _get_default_company_id(connection) -> uuid.UUID:
    """Get or create a default company for backfilling orphaned records."""
    # Try to find an existing company
    result = connection.execute(sa.text("SELECT id FROM companies LIMIT 1")).fetchone()
    if result:
        return result[0]
    # Create a default company if none exists
    default_id = uuid.uuid4()
    connection.execute(
        sa.text("""
            INSERT INTO companies (id, name, onboarding_completed, onboarding_step, status, created_at, updated_at)
            VALUES (:id, 'Default Company', false, 1, 'ACTIVE', NOW(), NOW())
            ON CONFLICT DO NOTHING
        """),
        {"id": default_id},
    )
    return default_id


def upgrade() -> None:
    connection = op.get_bind()
    default_company_id = _get_default_company_id(connection)

    # 1. SecurityPolicy: backfill company_id for existing records, then make NOT NULL
    op.execute(
        sa.text("UPDATE security_policies SET company_id = :cid WHERE company_id IS NULL").bindparams(cid=default_company_id)
    )

    with op.batch_alter_table("security_policies") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=False)

    op.create_unique_constraint(
        "uq_security_policies_company_id", "security_policies", ["company_id"]
    )

    op.create_index(
        "ix_security_policies_company_id", "security_policies", ["company_id"], unique=False
    )

    # 2. SecurityRole: backfill company_id for existing records, then make NOT NULL
    op.execute(
        sa.text("UPDATE security_roles SET company_id = :cid WHERE company_id IS NULL").bindparams(cid=default_company_id)
    )

    with op.batch_alter_table("security_roles") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=False)

    # Unique role_code per company (not global)
    op.create_unique_constraint(
        "uq_security_roles_company_id_role_code", "security_roles", ["company_id", "role_code"]
    )

    op.create_index(
        "ix_security_roles_company_id", "security_roles", ["company_id"], unique=False
    )

    # 3. IPWhitelist: backfill company_id for existing records, then make NOT NULL
    op.execute(
        sa.text("UPDATE ip_whitelist SET company_id = :cid WHERE company_id IS NULL").bindparams(cid=default_company_id)
    )

    with op.batch_alter_table("ip_whitelist") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=False)

    op.create_index(
        "ix_ip_whitelist_company_id", "ip_whitelist", ["company_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ip_whitelist_company_id", table_name="ip_whitelist")
    op.drop_index("ix_security_roles_company_id", table_name="security_roles")
    op.drop_index("ix_security_policies_company_id", table_name="security_policies")

    op.drop_constraint("uq_security_roles_company_id_role_code", "security_roles", type_="unique")
    op.drop_constraint("uq_security_policies_company_id", "security_policies", type_="unique")

    with op.batch_alter_table("ip_whitelist") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=True)

    with op.batch_alter_table("security_roles") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=True)

    with op.batch_alter_table("security_policies") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=True)