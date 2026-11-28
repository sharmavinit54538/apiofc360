"""Complete payment batch lifecycle columns, relationships, and safe backfill

Revision ID: b4e8f1c29d10
Revises: a9f3e2c81b04
Create Date: 2026-11-27 19:40:00.000000

"""
from __future__ import annotations

import hashlib
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b4e8f1c29d10"
down_revision: Union[str, None] = "a9f3e2c81b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. payment_batches columns
    pb_cols = {c["name"] for c in insp.get_columns("payment_batches", schema="public")}
    add_pb_cols = [
        ("period_id", sa.Column("period_id", postgresql.UUID(as_uuid=True), nullable=True)),
        ("currency", sa.Column("currency", sa.String(length=3), nullable=False, server_default=sa.text("'INR'"))),
        ("gross_amount_paise", sa.Column("gross_amount_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("held_amount_paise", sa.Column("held_amount_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("paid_amount_paise", sa.Column("paid_amount_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("failed_amount_paise", sa.Column("failed_amount_paise", sa.BigInteger(), nullable=False, server_default=sa.text("0"))),
        ("submitted_by", sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("submitted_at", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True)),
        ("reconciled_by", sa.Column("reconciled_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("reconciled_at", sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True)),
        ("bank_file_id", sa.Column("bank_file_id", postgresql.UUID(as_uuid=True), nullable=True)),
    ]
    for col_name, col_def in add_pb_cols:
        if col_name not in pb_cols:
            op.add_column("payment_batches", col_def)

    pb_fks = {fk["name"] for fk in insp.get_foreign_keys("payment_batches", schema="public") if fk.get("name")}
    pb_fk_defs = [
        ("fk_payment_batches_period_id", "payment_batches", "payroll_periods", ["period_id"], ["id"], "SET NULL"),
        ("fk_payment_batches_submitted_by", "payment_batches", "users", ["submitted_by"], ["id"], "SET NULL"),
        ("fk_payment_batches_reconciled_by", "payment_batches", "users", ["reconciled_by"], ["id"], "SET NULL"),
        ("fk_payment_batches_bank_file_id", "payment_batches", "payment_batch_bank_files", ["bank_file_id"], ["id"], "SET NULL"),
    ]
    for fk_name, src, ref, local_cols, remote_cols, ondelete in pb_fk_defs:
        if fk_name not in pb_fks:
            op.create_foreign_key(fk_name, src, ref, local_cols, remote_cols, ondelete=ondelete)

    pb_indexes = {idx["name"] for idx in insp.get_indexes("payment_batches", schema="public") if idx.get("name")}
    if "ix_payment_batches_period_id" not in pb_indexes:
        op.create_index("ix_payment_batches_period_id", "payment_batches", ["period_id"])

    # 2. payment_batch_items columns
    pbi_cols = {c["name"] for c in insp.get_columns("payment_batch_items", schema="public")}
    add_pbi_cols = [
        ("payment_reference", sa.Column("payment_reference", sa.String(length=120), nullable=True)),
        ("bank_name", sa.Column("bank_name", sa.String(length=120), nullable=True)),
        ("payment_date", sa.Column("payment_date", sa.DateTime(timezone=True), nullable=True)),
        ("failure_code", sa.Column("failure_code", sa.String(length=50), nullable=True)),
        ("held_by", sa.Column("held_by", postgresql.UUID(as_uuid=True), nullable=True)),
        ("held_at", sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)),
        ("retry_reason", sa.Column("retry_reason", sa.String(length=500), nullable=True)),
        ("last_retry_at", sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True)),
        ("reconciliation_status", sa.Column("reconciliation_status", sa.String(length=30), nullable=False, server_default=sa.text("'PENDING'"))),
    ]
    for col_name, col_def in add_pbi_cols:
        if col_name not in pbi_cols:
            op.add_column("payment_batch_items", col_def)

    pbi_fks = {fk["name"] for fk in insp.get_foreign_keys("payment_batch_items", schema="public") if fk.get("name")}
    if "fk_payment_batch_items_held_by" not in pbi_fks:
        op.create_foreign_key(
            "fk_payment_batch_items_held_by",
            "payment_batch_items",
            "users",
            ["held_by"],
            ["id"],
            ondelete="SET NULL",
        )

    # 3. payment_batch_bank_files columns
    bf_cols = {c["name"] for c in insp.get_columns("payment_batch_bank_files", schema="public")}
    add_bf_cols = [
        ("file_size_bytes", sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0"))),
        ("sha256_checksum", sa.Column("sha256_checksum", sa.String(length=64), nullable=True)),
        ("generated_by", sa.Column("generated_by", postgresql.UUID(as_uuid=True), nullable=True)),
    ]
    for col_name, col_def in add_bf_cols:
        if col_name not in bf_cols:
            op.add_column("payment_batch_bank_files", col_def)

    bf_fks = {fk["name"] for fk in insp.get_foreign_keys("payment_batch_bank_files", schema="public") if fk.get("name")}
    if "fk_payment_batch_bank_files_generated_by" not in bf_fks:
        op.create_foreign_key(
            "fk_payment_batch_bank_files_generated_by",
            "payment_batch_bank_files",
            "users",
            ["generated_by"],
            ["id"],
            ondelete="SET NULL",
        )

    # 4. Safe, idempotent backfill from verified existing payroll records (zero fabricated transactions)
    # 4a. Backfill period_id from payroll_runs
    bind.execute(sa.text("""
        UPDATE payment_batches pb
        SET period_id = pr.period_id
        FROM payroll_runs pr
        WHERE pb.run_id = pr.id
          AND pb.period_id IS NULL
          AND pr.period_id IS NOT NULL
    """))

    # 4b. Backfill company_id from payroll_runs if ever null
    bind.execute(sa.text("""
        UPDATE payment_batches pb
        SET company_id = pr.company_id
        FROM payroll_runs pr
        WHERE pb.run_id = pr.id
          AND pb.company_id IS NULL
          AND pr.company_id IS NOT NULL
    """))

    # 4c. Backfill aggregate financial breakdowns strictly from verified payment_batch_items
    bind.execute(sa.text("""
        WITH item_sums AS (
            SELECT
                batch_id,
                COUNT(*) AS all_count,
                COUNT(*) FILTER (WHERE UPPER(status) <> 'HELD') AS payable_count,
                COALESCE(SUM(amount_paise), 0) AS gross_sum,
                COALESCE(SUM(amount_paise) FILTER (WHERE UPPER(status) <> 'HELD'), 0) AS payable_sum,
                COALESCE(SUM(amount_paise) FILTER (WHERE UPPER(status) = 'HELD'), 0) AS held_sum,
                COALESCE(SUM(amount_paise) FILTER (WHERE UPPER(status) IN ('SUCCESS', 'PAID')), 0) AS paid_sum,
                COALESCE(SUM(amount_paise) FILTER (WHERE UPPER(status) = 'FAILED'), 0) AS failed_sum
            FROM payment_batch_items
            GROUP BY batch_id
        )
        UPDATE payment_batches pb
        SET
            gross_amount_paise = s.gross_sum,
            held_amount_paise = s.held_sum,
            paid_amount_paise = s.paid_sum,
            failed_amount_paise = s.failed_sum,
            total_amount_paise = CASE WHEN pb.total_amount_paise = 0 THEN s.payable_sum ELSE pb.total_amount_paise END,
            total_records = CASE WHEN pb.total_records = 0 THEN s.payable_count ELSE pb.total_records END
        FROM item_sums s
        WHERE pb.id = s.batch_id
    """))

    # 4d. Backfill submitted_by / submitted_at from verified payroll_audit_logs (action = 'SUBMIT')
    bind.execute(sa.text("""
        WITH latest_submit AS (
            SELECT DISTINCT ON (entity_id)
                entity_id,
                actor_id,
                created_at
            FROM payroll_audit_logs
            WHERE entity_type = 'PaymentBatch'
              AND UPPER(action) = 'SUBMIT'
            ORDER BY entity_id, created_at DESC
        )
        UPDATE payment_batches pb
        SET
            submitted_by = COALESCE(pb.submitted_by, ls.actor_id),
            submitted_at = COALESCE(pb.submitted_at, ls.created_at)
        FROM latest_submit ls
        WHERE pb.id = ls.entity_id
    """))

    # 4e. Backfill reconciled_by / reconciled_at from verified payroll_audit_logs (action = 'RECONCILE')
    bind.execute(sa.text("""
        WITH latest_reconcile AS (
            SELECT DISTINCT ON (entity_id)
                entity_id,
                actor_id,
                created_at
            FROM payroll_audit_logs
            WHERE entity_type = 'PaymentBatch'
              AND UPPER(action) = 'RECONCILE'
            ORDER BY entity_id, created_at DESC
        )
        UPDATE payment_batches pb
        SET
            reconciled_by = COALESCE(pb.reconciled_by, lr.actor_id),
            reconciled_at = COALESCE(pb.reconciled_at, lr.created_at)
        FROM latest_reconcile lr
        WHERE pb.id = lr.entity_id
    """))

    # 4f. Backfill latest bank_file_id on payment_batches
    bind.execute(sa.text("""
        WITH latest_bf AS (
            SELECT DISTINCT ON (batch_id)
                id,
                batch_id
            FROM payment_batch_bank_files
            ORDER BY batch_id, created_at DESC
        )
        UPDATE payment_batches pb
        SET bank_file_id = lbf.id
        FROM latest_bf lbf
        WHERE pb.id = lbf.batch_id
          AND pb.bank_file_id IS NULL
    """))

    # 4g. Backfill item bank_name (non-encrypted column on employee_bank_accounts),
    # payment_reference, payment_date, and reconciliation_status from verified data
    bind.execute(sa.text("""
        WITH primary_bank AS (
            SELECT DISTINCT ON (employee_id)
                employee_id,
                bank_name
            FROM employee_bank_accounts
            ORDER BY employee_id, is_primary DESC, updated_at DESC
        )
        UPDATE payment_batch_items pbi
        SET bank_name = COALESCE(pbi.bank_name, pbank.bank_name)
        FROM primary_bank pbank
        WHERE pbi.employee_id = pbank.employee_id
          AND pbi.bank_name IS NULL
    """))

    bind.execute(sa.text("""
        UPDATE payment_batch_items pbi
        SET
            payment_reference = COALESCE(pbi.payment_reference, pbi.utr_number, pbi.transaction_ref),
            payment_date = CASE
                WHEN pbi.payment_date IS NOT NULL THEN pbi.payment_date
                WHEN UPPER(pbi.status) IN ('SUCCESS', 'PAID') THEN COALESCE(pbi.reconciled_at, pb.submitted_at)
                ELSE NULL
            END,
            reconciliation_status = CASE
                WHEN pbi.reconciled_at IS NOT NULL OR UPPER(pb.status) = 'RECONCILED' THEN 'RECONCILED'
                WHEN UPPER(pbi.status) = 'HELD' THEN 'HELD'
                WHEN UPPER(pbi.status) = 'FAILED' THEN 'UNRECONCILED'
                WHEN UPPER(pbi.status) IN ('SUCCESS', 'PAID') THEN 'MATCHED'
                ELSE 'PENDING'
            END
        FROM payment_batches pb
        WHERE pbi.batch_id = pb.id
    """))

    # 4h. Backfill sha256_checksum & file_size_bytes for existing bank files
    bank_files = bind.execute(sa.text(
        "SELECT id, file_content, sha256_checksum, file_size_bytes FROM payment_batch_bank_files WHERE file_content IS NOT NULL"
    )).fetchall()
    for row in bank_files:
        raw_bytes = (row.file_content or "").encode("utf-8")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        size = len(raw_bytes)
        if not row.sha256_checksum or not row.file_size_bytes:
            bind.execute(
                sa.text(
                    "UPDATE payment_batch_bank_files SET sha256_checksum = :sha, file_size_bytes = :sz WHERE id = :fid"
                ),
                {"sha": digest, "sz": size, "fid": row.id},
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    bf_fks = {fk["name"] for fk in insp.get_foreign_keys("payment_batch_bank_files", schema="public") if fk.get("name")}
    if "fk_payment_batch_bank_files_generated_by" in bf_fks:
        op.drop_constraint("fk_payment_batch_bank_files_generated_by", "payment_batch_bank_files", type_="foreignkey")
    bf_cols = {c["name"] for c in insp.get_columns("payment_batch_bank_files", schema="public")}
    for col in ("generated_by", "sha256_checksum", "file_size_bytes"):
        if col in bf_cols:
            op.drop_column("payment_batch_bank_files", col)

    pbi_fks = {fk["name"] for fk in insp.get_foreign_keys("payment_batch_items", schema="public") if fk.get("name")}
    if "fk_payment_batch_items_held_by" in pbi_fks:
        op.drop_constraint("fk_payment_batch_items_held_by", "payment_batch_items", type_="foreignkey")
    pbi_cols = {c["name"] for c in insp.get_columns("payment_batch_items", schema="public")}
    for col in (
        "reconciliation_status",
        "last_retry_at",
        "retry_reason",
        "held_at",
        "held_by",
        "failure_code",
        "payment_date",
        "bank_name",
        "payment_reference",
    ):
        if col in pbi_cols:
            op.drop_column("payment_batch_items", col)

    pb_indexes = {idx["name"] for idx in insp.get_indexes("payment_batches", schema="public") if idx.get("name")}
    if "ix_payment_batches_period_id" in pb_indexes:
        op.drop_index("ix_payment_batches_period_id", table_name="payment_batches")

    pb_fks = {fk["name"] for fk in insp.get_foreign_keys("payment_batches", schema="public") if fk.get("name")}
    for fk_name in (
        "fk_payment_batches_bank_file_id",
        "fk_payment_batches_reconciled_by",
        "fk_payment_batches_submitted_by",
        "fk_payment_batches_period_id",
    ):
        if fk_name in pb_fks:
            op.drop_constraint(fk_name, "payment_batches", type_="foreignkey")

    pb_cols = {c["name"] for c in insp.get_columns("payment_batches", schema="public")}
    for col in (
        "bank_file_id",
        "reconciled_at",
        "reconciled_by",
        "submitted_at",
        "submitted_by",
        "failed_amount_paise",
        "paid_amount_paise",
        "held_amount_paise",
        "gross_amount_paise",
        "currency",
        "period_id",
    ):
        if col in pb_cols:
            op.drop_column("payment_batches", col)
