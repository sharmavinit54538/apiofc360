"""Read-only schema audit. Outputs metadata and SQLSTATE only, never row data."""
import asyncio
import json
from pathlib import Path
import sys

from alembic.migration import MigrationContext
from sqlalchemy import Column, inspect, select, text
from sqlalchemy.exc import DBAPIError

import app.models
from app.db.base import Base
from app.db.database import engine

TABLES = ("companies", "employees", "employee_bank_accounts", "assets",
          "asset_assignment_history", "asset_maintenance_records", "asset_requests",
          "asset_damage_reports")


def audit(conn):
    inspector = inspect(conn)
    context = MigrationContext.configure(conn)
    result = {}
    for name in TABLES:
        model = Base.metadata.tables.get(name)
        if model is None:
            continue
        if not inspector.has_table(name):
            result[name] = {"missing_table": True}
            continue
        columns = {c["name"]: c for c in inspector.get_columns(name)}
        indexes = inspector.get_indexes(name)
        fks = inspector.get_foreign_keys(name)
        unique = inspector.get_unique_constraints(name)
        checks = inspector.get_check_constraints(name)
        mismatches = []
        for col in model.c:
            actual = columns.get(col.name)
            if actual is None:
                mismatches.append({"column": col.name, "issue": "missing"})
                continue
            if context.impl.compare_type(Column(col.name, actual['type']), col):
                mismatches.append({"column": col.name, "issue": "type", "actual": str(actual['type']), "expected": str(col.type)})
            if actual['nullable'] != col.nullable:
                mismatches.append({"column": col.name, "issue": "nullable", "actual": actual['nullable'], "expected": col.nullable})
        for idx in model.indexes:
            actual = next((i for i in indexes if i['name'] == idx.name), None)
            expected = [c.name for c in idx.columns]
            if actual is None or actual['column_names'] != expected or bool(actual['unique']) != idx.unique:
                mismatches.append({"index": idx.name, "issue": "definition", "expected_columns": expected, "unique": idx.unique})
        actual_pk = inspector.get_pk_constraint(name)
        if actual_pk['constrained_columns'] != [c.name for c in model.primary_key.columns]:
            mismatches.append({'primary_key': name, 'issue': 'definition'})
        for fk in model.foreign_key_constraints:
            signature = ([c.name for c in fk.columns], fk.referred_table.name,
                         [e.column.name for e in fk.elements], fk.ondelete)
            if not any((f['constrained_columns'], f['referred_table'], f['referred_columns'], f['options'].get('ondelete')) == signature for f in fks):
                mismatches.append({"foreign_key": str(fk.name), "issue": "definition", "expected": signature})
        for constraint in model.constraints:
            if constraint.__class__.__name__ == 'UniqueConstraint':
                cols = [c.name for c in constraint.columns]
                if not any(u['column_names'] == cols for u in unique + [i for i in indexes if i['unique']]):
                    mismatches.append({"unique": str(constraint.name), "issue": "missing", "columns": cols})
            if constraint.__class__.__name__ == 'CheckConstraint':
                if not any(c['name'] == constraint.name for c in checks):
                    mismatches.append({"check": str(constraint.name), "issue": "missing"})
        result[name] = {"mismatches": mismatches,
                       "columns": [{**c, 'type': str(c['type'])} for c in columns.values()],
                       "indexes": indexes, "foreign_keys": fks, "unique_constraints": unique,
                       "check_constraints": checks, "primary_key": inspector.get_pk_constraint(name)}
    return result


async def pii_counts(conn):
    from app.models.employee import ENCRYPTED_EMPLOYEE_PII_FIELDS
    from app.core.field_encryption import ENCRYPTED_VALUE_PREFIX
    result = {}
    for field in ENCRYPTED_EMPLOYEE_PII_FIELDS:
        result[field] = dict((await conn.execute(text(
            f'SELECT count(*) FILTER (WHERE {field} IS NOT NULL AND {field} NOT LIKE :prefix) AS legacy_unencrypted, '
            f'count(*) FILTER (WHERE {field} IS NOT NULL AND {field}_blind_idx IS NULL) AS missing_index, '
            f'count(*) FILTER (WHERE {field} IS NOT NULL AND company_id IS NULL) AS missing_tenant FROM employees'
        ), {'prefix': ENCRYPTED_VALUE_PREFIX + '%'})).mappings().one())
    result['null_statutory_flags'] = dict((await conn.execute(text(
        'SELECT count(*) FILTER (WHERE is_pf_eligible IS NULL) AS is_pf_eligible, '
        'count(*) FILTER (WHERE is_international_worker IS NULL) AS is_international_worker, '
        'count(*) FILTER (WHERE pf_wage_ceiling_applicable IS NULL) AS pf_wage_ceiling_applicable FROM employees'
    ))).mappings().one())
    return result


async def main():
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            result = {"revision": list((await conn.execute(text('SELECT version_num FROM alembic_version'))).scalars()),
                      "tables": await conn.run_sync(audit), "sql_errors": []}
            if not any(m.get('issue') == 'missing' for m in result['tables']['employees']['mismatches']):
                result['pii_counts'] = await pii_counts(conn)
            await conn.rollback()
            for name in ('companies', 'employees', 'assets'):
                await conn.execute(text('SET TRANSACTION READ ONLY'))
                try:
                    await conn.execute(select(Base.metadata.tables[name]).limit(0))
                except DBAPIError as exc:
                    result['sql_errors'].append({'table': name, 'sqlstate': getattr(exc.orig, 'sqlstate', None),
                                                  'message': str(exc.orig)})
                finally:
                    await conn.rollback()
        path = Path(sys.argv[1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'revision': result['revision'], 'mismatches': {k: v.get('mismatches', v) for k, v in result['tables'].items()}, 'sql_errors': result['sql_errors'], 'pii_counts': result.get('pii_counts')}, indent=2))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
