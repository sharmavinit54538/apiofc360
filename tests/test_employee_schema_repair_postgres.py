"""Rehearse repair and encrypted backfill against migrated disposable PostgreSQL."""
import importlib.util
from pathlib import Path
import json
import uuid
from datetime import date

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.field_encryption import encrypt_value, decrypt_value, hmac_sha256_blind_index
from app.db.database import engine
from app.models.company import Company
from app.models.employee import Employee, ENCRYPTED_EMPLOYEE_PII_FIELDS
from scripts.asset_verify_schema import audit
from scripts.backfill_encrypted_pii import backfill_employees
from tests.test_asset_management_comprehensive import db_session  # disposable guard

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('employee_repair', ROOT / 'alembic/versions/41a_employee_schema_contract.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def upgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
        repair.upgrade()


@pytest_asyncio.fixture
async def isolated_schema(db_session):
    # DDL, data and revision-independent rehearsal all roll back together.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


async def seed(connection, *, tenant=True):
    session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint')
    company = Company(name='Encrypted migration fixture')
    session.add(company)
    await session.flush()
    employee = Employee(employee_id=uuid.uuid4().hex[:16], first_name='Migration', last_name='Fixture',
                        personal_email=f'{uuid.uuid4().hex}@example.test', phone='0000000000',
                        department='Test', designation='Test', joining_date=date(2026, 1, 1),
                        company_id=company.id if tenant else None,
                        **{field: f'TEST-{field}' for field in ENCRYPTED_EMPLOYEE_PII_FIELDS})
    session.add(employee)
    await session.commit()
    await session.close()
    return employee


async def test_repair_missing_columns_indexes_and_types_preserves_ciphertext(isolated_schema):
    conn = isolated_schema
    employee = await seed(conn)
    fields = ENCRYPTED_EMPLOYEE_PII_FIELDS
    before = dict((await conn.execute(text('SELECT ' + ', '.join(fields) + ' FROM employees WHERE id=:id'), {'id': employee.id})).mappings().one())
    for field in fields:
        await conn.execute(text(f'ALTER TABLE employees DROP COLUMN {field}_blind_idx'))
        await conn.execute(text(f'ALTER TABLE employees ALTER COLUMN {field} TYPE varchar(512)'))
    for flag in repair.FLAGS:
        await conn.execute(text(f'ALTER TABLE employees ALTER COLUMN {flag} DROP NOT NULL'))
    before_audit = await conn.run_sync(audit)
    async with conn.begin_nested() as savepoint:
        with pytest.raises(DBAPIError) as error:
            await conn.execute(select(Employee).limit(0))
        assert error.value.orig.sqlstate == '42703'
        await savepoint.rollback()
    evidence = ROOT / 'verification/asset-pg-20261116/reproduced-drift.json'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({'sqlstate': '42703', 'message': str(error.value.orig),
                                   'mismatches': before_audit['employees']['mismatches']}, indent=2))
    await conn.run_sync(upgrade)
    await conn.run_sync(upgrade)
    assert (await conn.run_sync(audit))['employees']['mismatches'] == []
    after = dict((await conn.execute(text('SELECT ' + ', '.join(fields) + ' FROM employees WHERE id=:id'), {'id': employee.id})).mappings().one())
    assert all(before[f] == after[f] and decrypt_value(after[f]) == f'TEST-{f}' for f in fields)
    async with AsyncSession(bind=conn, join_transaction_mode='create_savepoint') as session:
        first = await backfill_employees(session, company_id=employee.company_id, batch_size=1)
        second = await backfill_employees(session, company_id=employee.company_id, batch_size=1)
    assert first['employee_indexes_updated'] == 5
    assert second['employee_indexes_updated'] == 0
    result = (await conn.execute(text('SELECT ' + ', '.join(f'{f}_blind_idx' for f in fields) + ' FROM employees WHERE id=:id'), {'id': employee.id})).mappings().one()
    assert all(result[f'{f}_blind_idx'] == hmac_sha256_blind_index(f'TEST-{f}', employee.company_id) for f in fields)


async def test_repair_refuses_unresolved_null_statutory_flags(isolated_schema):
    conn = isolated_schema
    employee = await seed(conn)
    await conn.execute(text('ALTER TABLE employees ALTER COLUMN is_pf_eligible DROP NOT NULL'))
    await conn.execute(text('UPDATE employees SET is_pf_eligible=NULL WHERE id=:id'), {'id': employee.id})
    with pytest.raises(RuntimeError, match='NULL rows require explicit review'):
        await conn.run_sync(upgrade)
    assert (await conn.execute(text('SELECT is_pf_eligible FROM employees WHERE id=:id'), {'id': employee.id})).scalar_one() is None


async def test_repair_refuses_incompatible_existing_index(isolated_schema):
    conn = isolated_schema
    await conn.execute(text('DROP INDEX ix_employees_company_aadhaar_blind_idx'))
    await conn.execute(text('CREATE INDEX ix_employees_company_aadhaar_blind_idx ON employees (aadhaar_number_blind_idx)'))
    with pytest.raises(RuntimeError, match='Incompatible index'):
        await conn.run_sync(upgrade)


async def test_backfill_dry_run_quarantines_bad_ciphertext_without_partial_row_write(isolated_schema):
    conn = isolated_schema
    employee = await seed(conn)
    await conn.execute(text('UPDATE employees SET aadhaar_number_blind_idx=NULL, passport_number=:bad WHERE id=:id'),
                       {'bad': 'enc:v1:missing-key:invalid', 'id': employee.id})
    # Use the exact version prefix from the existing encryption implementation.
    from app.core.field_encryption import ENCRYPTED_VALUE_PREFIX
    corrupt = ENCRYPTED_VALUE_PREFIX + 'missing-key:invalid'
    await conn.execute(text('UPDATE employees SET passport_number=:bad WHERE id=:id'), {'bad': corrupt, 'id': employee.id})
    issues = []
    async with AsyncSession(bind=conn, join_transaction_mode='create_savepoint') as session:
        stats = await backfill_employees(session, company_id=employee.company_id, issues=issues)
    assert stats['rows_quarantined'] == 1
    assert issues == [{'table': 'employees', 'id': str(employee.id), 'reason': 'key_or_ciphertext_error'}]
    row = (await conn.execute(text('SELECT aadhaar_number_blind_idx, passport_number FROM employees WHERE id=:id'), {'id': employee.id})).one()
    assert row[0] is None and row[1] == corrupt
    await conn.execute(text('UPDATE employees SET passport_number=:value WHERE id=:id'), {'value': encrypt_value('TEST-passport_number'), 'id': employee.id})
    async with AsyncSession(bind=conn, join_transaction_mode='create_savepoint') as session:
        stats = await backfill_employees(session, company_id=employee.company_id, dry_run=True)
    assert stats['employee_indexes_updated'] == 1 and stats['rows_quarantined'] == 0
    assert (await conn.execute(text('SELECT aadhaar_number_blind_idx FROM employees WHERE id=:id'), {'id': employee.id})).scalar_one() is None


async def test_backfill_missing_tenant_is_not_silently_marked_complete(isolated_schema):
    conn = isolated_schema
    employee = await seed(conn, tenant=False)
    issues = []
    async with AsyncSession(bind=conn, join_transaction_mode='create_savepoint') as session:
        stats = await backfill_employees(session, issues=issues)
    assert stats['rows_quarantined'] == 1
    assert {'table': 'employees', 'id': str(employee.id), 'reason': 'missing_tenant'} in issues
