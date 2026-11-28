"""enterprise payslip branding settings and verification documents

Revision ID: a9f3e2c81b04
Revises: 7489259cd72d
Create Date: 2026-11-27 16:54:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a9f3e2c81b04"
down_revision: Union[str, None] = "7489259cd72d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    company_cols = {c["name"] for c in insp.get_columns("companies", schema="public")}
    if "payslip_settings" not in company_cols:
        op.add_column("companies", sa.Column("payslip_settings", sa.JSON(), nullable=True))

    payslip_cols = {c["name"] for c in insp.get_columns("payslips", schema="public")}
    add_payslip_cols = [
        ("document_id", sa.Column("document_id", sa.String(length=64), nullable=True)),
        ("document_version", sa.Column("document_version", sa.Integer(), nullable=False, server_default=sa.text("1"))),
        ("status", sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'GENERATED'"))),
        ("sha256_hash", sa.Column("sha256_hash", sa.String(length=64), nullable=True)),
        ("verification_token", sa.Column("verification_token", sa.String(length=128), nullable=True)),
        ("snapshot_json", sa.Column("snapshot_json", sa.JSON(), nullable=True)),
        ("released_at", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True)),
        ("released_by", sa.Column("released_by", postgresql.UUID(as_uuid=True), nullable=True)),
    ]
    for col_name, col_def in add_payslip_cols:
        if col_name not in payslip_cols:
            op.add_column("payslips", col_def)

    payslip_fks = {fk["name"] for fk in insp.get_foreign_keys("payslips", schema="public") if fk.get("name")}
    if "fk_payslips_released_by_users" not in payslip_fks:
        op.create_foreign_key(
            "fk_payslips_released_by_users",
            "payslips",
            "users",
            ["released_by"],
            ["id"],
            ondelete="SET NULL",
        )

    payslip_uqs = {uq["name"] for uq in insp.get_unique_constraints("payslips", schema="public") if uq.get("name")}
    if "uq_payslips_document_id" not in payslip_uqs:
        op.create_unique_constraint("uq_payslips_document_id", "payslips", ["document_id"])
    if "uq_payslips_verification_token" not in payslip_uqs:
        op.create_unique_constraint("uq_payslips_verification_token", "payslips", ["verification_token"])

    tables = set(insp.get_table_names(schema="public"))
    if "payslip_documents" not in tables:
        op.create_table(
            "payslip_documents",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("payslip_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("payslip_number", sa.String(length=40), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'FINAL'")),
            sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("sha256_hash", sa.String(length=64), nullable=False),
            sa.Column("verification_token", sa.String(length=128), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id", name="pk_payslip_documents"),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_payslip_docs_company_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["payslip_id"], ["payslips.id"], name="fk_payslip_docs_payslip_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["payroll_run_id"], ["payroll_runs.id"], name="fk_payslip_docs_run_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name="fk_payslip_docs_emp_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["generated_by"], ["users.id"], name="fk_payslip_docs_generated_by", ondelete="SET NULL"),
            sa.UniqueConstraint("document_id", name="uq_payslip_documents_document_id"),
            sa.UniqueConstraint("verification_token", name="uq_payslip_documents_verification_token"),
            sa.UniqueConstraint("payslip_id", "version_number", name="uq_payslip_document_version"),
        )
        op.create_index("ix_payslip_documents_company_id", "payslip_documents", ["company_id"], unique=False)
        op.create_index("ix_payslip_documents_payslip_id", "payslip_documents", ["payslip_id"], unique=False)
        op.create_index("ix_payslip_documents_verification_token", "payslip_documents", ["verification_token"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names(schema="public"))
    if "payslip_documents" in tables:
        op.drop_table("payslip_documents")

    payslip_uqs = {uq["name"] for uq in insp.get_unique_constraints("payslips", schema="public") if uq.get("name")}
    for uq_name in ("uq_payslips_verification_token", "uq_payslips_document_id"):
        if uq_name in payslip_uqs:
            op.drop_constraint(uq_name, "payslips", type_="unique")

    payslip_fks = {fk["name"] for fk in insp.get_foreign_keys("payslips", schema="public") if fk.get("name")}
    if "fk_payslips_released_by_users" in payslip_fks:
        op.drop_constraint("fk_payslips_released_by_users", "payslips", type_="foreignkey")

    payslip_cols = {c["name"] for c in insp.get_columns("payslips", schema="public")}
    for col_name in ("released_by", "released_at", "snapshot_json", "verification_token", "sha256_hash", "status", "document_version", "document_id"):
        if col_name in payslip_cols:
            op.drop_column("payslips", col_name)

    company_cols = {c["name"] for c in insp.get_columns("companies", schema="public")}
    if "payslip_settings" in company_cols:
        op.drop_column("companies", "payslip_settings")
