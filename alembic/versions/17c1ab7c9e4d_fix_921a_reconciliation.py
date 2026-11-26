"""Fix 921a migration: Remove synthetic Default Company assignment and add reconciliation tracking.

This migration addresses the issues in 921a_security_policy_tenant_isolation:
- Removes arbitrary first-company assignment and synthetic "Default Company" creation
- Makes company_id nullable again for historical records
- Adds reconciliation tracking for ambiguous historical rows
- Preserves all data for manual reconciliation

Revision ID: 17c1ab7c9e4d
Revises: 921a_security_policy_tenant_isolation
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "17c1ab7c9e4d"
down_revision = "921a_security_policy_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # 1. Identify the synthetic "Default Company" if it exists
    default_company = connection.execute(
        sa.text("SELECT id FROM companies WHERE name = 'Default Company' AND onboarding_completed = false")
    ).fetchone()
    
    default_company_id = default_company[0] if default_company else None

    # 2. Add reconciliation tracking columns to track ambiguous records
    # SecurityPolicy: add reconciliation_needed flag
    op.add_column(
        "security_policies",
        sa.Column("reconciliation_needed", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column(
        "security_policies",
        sa.Column("reconciliation_notes", sa.Text(), nullable=True)
    )

    # SecurityRole: add reconciliation_needed flag
    op.add_column(
        "security_roles",
        sa.Column("reconciliation_needed", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column(
        "security_roles",
        sa.Column("reconciliation_notes", sa.Text(), nullable=True)
    )

    # IPWhitelist: add reconciliation_needed flag
    op.add_column(
        "ip_whitelist",
        sa.Column("reconciliation_needed", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column(
        "ip_whitelist",
        sa.Column("reconciliation_notes", sa.Text(), nullable=True)
    )

    # 3. Mark records that were assigned to the synthetic Default Company as needing reconciliation
    if default_company_id:
        connection.execute(
            sa.text("""
                UPDATE security_policies 
                SET reconciliation_needed = true, 
                    reconciliation_notes = 'Assigned to synthetic Default Company during 921a migration. Manual reconciliation required.'
                WHERE company_id = :cid
            """),
            {"cid": default_company_id}
        )

        connection.execute(
            sa.text("""
                UPDATE security_roles 
                SET reconciliation_needed = true, 
                    reconciliation_notes = 'Assigned to synthetic Default Company during 921a migration. Manual reconciliation required.'
                WHERE company_id = :cid
            """),
            {"cid": default_company_id}
        )

        connection.execute(
            sa.text("""
                UPDATE ip_whitelist 
                SET reconciliation_needed = true, 
                    reconciliation_notes = 'Assigned to synthetic Default Company during 921a migration. Manual reconciliation required.'
                WHERE company_id = :cid
            """),
            {"cid": default_company_id}
        )

    # 4. Also mark records that still have NULL company_id (if any survived) as needing reconciliation
    connection.execute(
        sa.text("""
            UPDATE security_policies 
            SET reconciliation_needed = true, 
                reconciliation_notes = 'Missing company_id after 921a migration. Manual reconciliation required.'
            WHERE company_id IS NULL
        """)
    )

    connection.execute(
        sa.text("""
            UPDATE security_roles 
            SET reconciliation_needed = true, 
                reconciliation_notes = 'Missing company_id after 921a migration. Manual reconciliation required.'
            WHERE company_id IS NULL
        """)
    )

    connection.execute(
        sa.text("""
            UPDATE ip_whitelist 
            SET reconciliation_needed = true, 
                reconciliation_notes = 'Missing company_id after 921a migration. Manual reconciliation required.'
            WHERE company_id IS NULL
        """)
    )

    # 5. Make company_id nullable again to allow proper reconciliation workflow
    # This allows operators to assign correct company_id or delete ambiguous records
    with op.batch_alter_table("security_policies") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=True)

    with op.batch_alter_table("security_roles") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=True)

    with op.batch_alter_table("ip_whitelist") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=True)

    # 6. Drop the unique constraint on security_policies.company_id since multiple companies
    # can now have policies, and we need to allow NULL during reconciliation
    op.drop_constraint("uq_security_policies_company_id", "security_policies", type_="unique")

    # 7. Create a reconciliation view for operators to find ambiguous records
    # Note: security_policies uses updated_at, not created_at
    op.execute(sa.text("""
        CREATE OR REPLACE VIEW security_reconciliation_queue AS
        SELECT 'security_policies' AS table_name, id, company_id, reconciliation_needed, reconciliation_notes, updated_at as created_at
        FROM security_policies WHERE reconciliation_needed = true
        UNION ALL
        SELECT 'security_roles' AS table_name, id, company_id, reconciliation_needed, reconciliation_notes, created_at
        FROM security_roles WHERE reconciliation_needed = true
        UNION ALL
        SELECT 'ip_whitelist' AS table_name, id, company_id, reconciliation_needed, reconciliation_notes, created_at
        FROM ip_whitelist WHERE reconciliation_needed = true
        ORDER BY table_name, created_at
    """))


def downgrade() -> None:
    # Drop the reconciliation view
    op.execute(sa.text("DROP VIEW IF EXISTS security_reconciliation_queue"))

    # Restore NOT NULL constraints (reverse of step 5)
    with op.batch_alter_table("ip_whitelist") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=False)

    with op.batch_alter_table("security_roles") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=False)

    with op.batch_alter_table("security_policies") as batch_op:
        batch_op.alter_column("company_id", existing_type=UUID(as_uuid=True), nullable=False)

    # Restore unique constraint
    op.create_unique_constraint(
        "uq_security_policies_company_id", "security_policies", ["company_id"]
    )

    # Drop reconciliation columns
    op.drop_column("ip_whitelist", "reconciliation_notes")
    op.drop_column("ip_whitelist", "reconciliation_needed")
    op.drop_column("security_roles", "reconciliation_notes")
    op.drop_column("security_roles", "reconciliation_needed")
    op.drop_column("security_policies", "reconciliation_notes")
    op.drop_column("security_policies", "reconciliation_needed")