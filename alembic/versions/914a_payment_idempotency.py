"""Protect initial payroll payment operations and linked replacement items.

Revision ID: 914a_payment_idempotency
Revises: 913a_settings_management
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "914a_payment_idempotency"
down_revision = "913a_settings_management"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    checks = {
        "duplicate initial batches": """
            SELECT run_id::text, string_agg(id::text, ',') AS ids FROM payment_batches
            WHERE retry_of_batch_id IS NULL GROUP BY company_id, run_id HAVING count(*) > 1
        """,
        "duplicate employee items": """
            SELECT batch_id::text, string_agg(id::text, ',') AS ids FROM payment_batch_items
            GROUP BY batch_id, employee_id HAVING count(*) > 1
        """,
        "ambiguous historical replacement sources": """
            SELECT child.id::text FROM payment_batch_items child
            JOIN payment_batches batch ON child.batch_id = batch.id
            LEFT JOIN payment_batch_items source ON source.repayout_batch_id = batch.id
                AND source.employee_id = child.employee_id
                AND source.batch_id = batch.retry_of_batch_id
            WHERE batch.retry_of_batch_id IS NOT NULL
            GROUP BY child.id HAVING count(source.id) <> 1
        """,
        "mismatched payment tenant": """
            SELECT item.id::text FROM payment_batch_items item
            JOIN payment_batches batch ON batch.id = item.batch_id
            JOIN payroll_runs run ON run.id = batch.run_id
            JOIN employees employee ON employee.id = item.employee_id
            WHERE item.company_id IS DISTINCT FROM batch.company_id
               OR batch.company_id IS DISTINCT FROM run.company_id
               OR employee.company_id IS DISTINCT FROM run.company_id
        """,
    }
    for description, sql in checks.items():
        conflicts = bind.execute(sa.text(sql)).fetchmany(20)
        if conflicts:
            raise RuntimeError(f"Payment safety migration blocked: {description}: {conflicts}. Review historical records; no rows were deleted or merged.")

    op.add_column("payment_batches", sa.Column("operation_key", sa.String(100), nullable=True))
    op.add_column("payment_batches", sa.Column("request_fingerprint", sa.String(64), nullable=True))
    bind.execute(sa.text("""UPDATE payment_batches SET operation_key = CASE
        WHEN retry_of_batch_id IS NULL THEN 'INITIAL' ELSE 'LEGACY_RETRY:' || id::text END"""))
    op.alter_column("payment_batches", "operation_key", nullable=False, server_default="INITIAL")
    op.create_unique_constraint("uq_payment_batch_operation", "payment_batches",
        ["company_id", "run_id", "operation_key"], postgresql_nulls_not_distinct=True)
    op.add_column("payment_batch_items", sa.Column("retry_source_item_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_payment_retry_source", "payment_batch_items", "payment_batch_items",
        ["retry_source_item_id"], ["id"], ondelete="RESTRICT")
    bind.execute(sa.text("""UPDATE payment_batch_items child SET retry_source_item_id = source.id
        FROM payment_batch_items source, payment_batches batch
        WHERE child.batch_id = batch.id AND batch.retry_of_batch_id = source.batch_id
          AND source.repayout_batch_id = batch.id AND source.employee_id = child.employee_id"""))
    op.create_unique_constraint("uq_payment_batch_employee", "payment_batch_items", ["batch_id", "employee_id"])
    op.create_unique_constraint("uq_payment_retry_source", "payment_batch_items", ["retry_source_item_id"])


def downgrade():
    op.drop_constraint("uq_payment_retry_source", "payment_batch_items", type_="unique")
    op.drop_constraint("uq_payment_batch_employee", "payment_batch_items", type_="unique")
    op.drop_constraint("fk_payment_retry_source", "payment_batch_items", type_="foreignkey")
    op.drop_column("payment_batch_items", "retry_source_item_id")
    op.drop_constraint("uq_payment_batch_operation", "payment_batches", type_="unique")
    op.drop_column("payment_batches", "request_fingerprint")
    op.drop_column("payment_batches", "operation_key")
