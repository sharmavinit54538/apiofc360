"""Verify the expense migration against real PostgreSQL legacy ledger rows.

Set EXPENSE_TEST_DATABASE_URL to a disposable PostgreSQL database. This test
creates a randomly named schema inside one rolled-back transaction; it never
reads application data or uses the configured application DATABASE_URL.
"""
from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
REVISION = ROOT / "alembic" / "versions" / "912a_expense_workflow.py"


def _revision():
    spec = importlib.util.spec_from_file_location("expense_workflow_migration", REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expense_migration_has_single_head_and_additive_offline_sql():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    # The expense revision is no longer the tip; later additive payroll
    # migrations merge the historical migration branches into one head.
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert "912a_expense_workflow" in {revision.revision for revision in scripts.iterate_revisions(heads[0], "base")}
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        _revision().upgrade()
    sql = output.getvalue().upper()
    assert "ADD COLUMN CURRENCY" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "FOREIGN KEY(PAID_BY) REFERENCES USERS (ID) ON DELETE SET NULL" in sql
    assert "DROP " not in sql
    assert "DELETE FROM" not in sql
    assert "UPDATE REIMBURSEMENT_CLAIMS" not in sql


def test_expense_migration_preserves_existing_postgresql_claims():
    url = os.environ.get("EXPENSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("EXPENSE_TEST_DATABASE_URL is required for real PostgreSQL migration validation")
    parsed = sa.engine.make_url(url)
    if parsed.get_backend_name() != "postgresql":
        pytest.fail("Expense migration integration requires PostgreSQL")
    engine = sa.create_engine(parsed.set(drivername="postgresql+psycopg2"))
    schema = "expense_migration_" + uuid.uuid4().hex
    company_id, user_id, employee_id, cycle_id = [uuid.uuid4() for _ in range(4)]
    claim_ids = [uuid.uuid4() for _ in range(4)]
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
                for table in ("companies", "users", "employees", "pay_cycles"):
                    connection.execute(sa.text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
                connection.execute(sa.text("""
                    CREATE TABLE reimbursement_claims (
                        id uuid PRIMARY KEY,
                        company_id uuid REFERENCES companies(id),
                        employee_id uuid NOT NULL REFERENCES employees(id),
                        pay_cycle_id uuid REFERENCES pay_cycles(id),
                        category varchar(100) NOT NULL,
                        amount numeric(14, 2) NOT NULL,
                        claim_date date NOT NULL,
                        status varchar(20) NOT NULL DEFAULT 'SUBMITTED',
                        payout_mode varchar(20) NOT NULL,
                        approved_by uuid REFERENCES users(id),
                        approved_at timestamptz,
                        created_at timestamptz NOT NULL DEFAULT now()
                    )
                """))
                connection.execute(sa.text("""
                    CREATE TABLE payroll_audit_logs (
                        id uuid PRIMARY KEY,
                        company_id uuid,
                        entity_type varchar(50) NOT NULL,
                        entity_id uuid,
                        created_at timestamptz NOT NULL DEFAULT now()
                    )
                """))
                for table, value in zip(
                    ("companies", "users", "employees", "pay_cycles"),
                    (company_id, user_id, employee_id, cycle_id),
                ):
                    connection.execute(sa.text(f"INSERT INTO {table} (id) VALUES (:id)"), {"id": value})
                for claim_id, status in zip(claim_ids, ("SUBMITTED", "APPROVED", "QUEUED", "PAID")):
                    connection.execute(sa.text("""
                        INSERT INTO reimbursement_claims
                        (id, company_id, employee_id, pay_cycle_id, category, amount,
                         claim_date, status, payout_mode, approved_by, approved_at)
                        VALUES (:id, :company, :employee, :cycle, 'TRAVEL', 2500.37,
                                '2026-11-10', :status, 'CYCLE', :user_id, '2026-11-11T10:00:00Z')
                    """), {
                        "id": claim_id, "company": company_id, "employee": employee_id,
                        "cycle": cycle_id, "status": status, "user_id": user_id,
                    })
                before = connection.execute(sa.text("SELECT * FROM reimbursement_claims ORDER BY id")).mappings().all()
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    _revision().upgrade()
                after = connection.execute(sa.text("SELECT * FROM reimbursement_claims ORDER BY id")).mappings().all()
                assert len(after) == 4
                for old, new in zip(before, after):
                    assert {key: new[key] for key in old} == dict(old)
                    assert new["currency"] == "INR"
                    assert new["deleted_at"] is None
                    assert new["payment_reference"] is None
                    assert new["paid_at"] is None
                inspector = sa.inspect(connection)
                foreign_keys = {tuple(fk["constrained_columns"]) for fk in inspector.get_foreign_keys("reimbursement_claims")}
                assert ("reviewed_by",) in foreign_keys
                assert ("paid_by",) in foreign_keys
                index_names = {index["name"] for index in inspector.get_indexes("reimbursement_claims")}
                assert {
                    "ix_reimbursement_claims_company_status_date",
                    "ix_reimbursement_claims_company_employee",
                    "ix_reimbursement_claims_company_payment",
                } <= index_names
                assert "ix_payroll_audit_logs_company_entity" in {
                    index["name"] for index in inspector.get_indexes("payroll_audit_logs")
                }
                with Operations.context(context), pytest.raises(RuntimeError, match="cannot be downgraded"):
                    _revision().downgrade()
                assert connection.scalar(sa.text("SELECT count(*) FROM reimbursement_claims")) == 4
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
