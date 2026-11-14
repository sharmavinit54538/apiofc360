"""Add expense workflow metadata to the existing reimbursement ledger.

Revision ID: 912a_expense_workflow
Revises: 911a_batch7_p3_features

All additions preserve existing claims, statuses, payroll links and approvals.
Historical claims were denominated in INR in the reimbursement API; the currency
default preserves that contract. Status/payment history uses payroll_audit_logs.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "912a_expense_workflow"
down_revision = "911a_batch7_p3_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reimbursement_claims", sa.Column(
        "currency", sa.String(3), nullable=False, server_default=sa.text("'INR'")
    ))
    for name, length in (
        ("merchant", 255), ("project_id", 100),
        ("payment_reference", 128), ("payment_method", 32),
    ):
        op.add_column("reimbursement_claims", sa.Column(name, sa.String(length), nullable=True))
    for name in ("reviewed_at", "paid_at", "deleted_at"):
        op.add_column("reimbursement_claims", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for name in ("reviewed_by", "paid_by"):
        op.add_column("reimbursement_claims", sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_reimbursement_claims_{name}_users"),
            "reimbursement_claims", "users", [name], ["id"], ondelete="SET NULL",
        )
    op.create_index(
        "ix_reimbursement_claims_company_status_date", "reimbursement_claims",
        ["company_id", "status", "claim_date"],
    )
    op.create_index(
        "ix_reimbursement_claims_company_employee", "reimbursement_claims",
        ["company_id", "employee_id", "created_at"],
    )
    op.create_index(
        "ix_reimbursement_claims_company_payment", "reimbursement_claims",
        ["company_id", "payment_reference"],
    )
    op.create_index(
        "ix_payroll_audit_logs_company_entity", "payroll_audit_logs",
        ["company_id", "entity_type", "entity_id", "created_at"],
    )


def downgrade() -> None:
    # Removing these columns would discard financial/payment history. Older
    # application releases can run with the additive columns still present.
    raise RuntimeError(
        "Expense workflow migration is data-preserving and cannot be downgraded; "
        "roll back the application while retaining the additive database schema."
    )
