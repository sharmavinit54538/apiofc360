#!/usr/bin/env python3
"""Idempotently encrypt legacy employee PII and maintain blind indexes.

Run after the additive schema migration and before removing old keys::

    python -m scripts.backfill_encrypted_pii --batch-size 250
    python -m scripts.backfill_encrypted_pii --dry-run
    python -m scripts.backfill_encrypted_pii --company-id <tenant-uuid>

The command intentionally uses lightweight Core tables instead of ORM encrypted
columns so it can distinguish legacy plaintext from ciphertext.  No identifier
values are logged.  Each batch commits independently and is safe to retry.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

from sqlalchemy import Column, MetaData, Table, Text, select, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.field_encryption import (
    decrypt_value,
    encrypt_value,
    hmac_sha256_blind_index,
    is_encrypted_value,
)


EMPLOYEE_PII_FIELDS = (
    "aadhaar_number",
    "pan_number",
    "uan_number",
    "passport_number",
    "voter_id",
)
BANK_PII_FIELDS = ("account_number", "ifsc_code")

_raw_metadata = MetaData()
_employees = Table(
    "employees",
    _raw_metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("company_id", PG_UUID(as_uuid=True)),
    *(Column(name, Text) for name in EMPLOYEE_PII_FIELDS),
    *(Column(f"{name}_blind_idx", Text) for name in EMPLOYEE_PII_FIELDS),
)
_bank_accounts = Table(
    "employee_bank_accounts",
    _raw_metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("employee_id", PG_UUID(as_uuid=True)),
    *(Column(name, Text) for name in BANK_PII_FIELDS),
)


def _empty_stats() -> dict[str, int]:
    return {
        "employees_scanned": 0,
        "employees_encrypted": 0,
        "employee_indexes_updated": 0,
        "bank_accounts_scanned": 0,
        "bank_values_encrypted": 0,
        "rows_unchanged": 0,
    }


async def backfill_employees(
    session: AsyncSession,
    *,
    batch_size: int = 250,
    dry_run: bool = False,
    company_id: uuid.UUID | None = None,
) -> dict[str, int]:
    stats = _empty_stats()
    offset = 0
    while True:
        stmt = select(_employees).order_by(_employees.c.id).limit(batch_size).offset(offset)
        if company_id is not None:
            stmt = stmt.where(_employees.c.company_id == company_id)
        rows = list((await session.execute(stmt)).mappings().all())
        if not rows:
            break

        for row in rows:
            stats["employees_scanned"] += 1
            changes: dict[str, Any] = {}
            encrypted_fields = 0
            index_fields = 0
            for field_name in EMPLOYEE_PII_FIELDS:
                stored = row[field_name]
                if is_encrypted_value(stored):
                    plaintext = decrypt_value(stored)
                else:
                    plaintext = stored
                    if stored is not None:
                        changes[field_name] = encrypt_value(stored)
                        encrypted_fields += 1

                blind_name = f"{field_name}_blind_idx"
                expected_index = hmac_sha256_blind_index(plaintext, row["company_id"])
                if row[blind_name] != expected_index:
                    changes[blind_name] = expected_index
                    index_fields += 1

            if changes:
                if not dry_run:
                    await session.execute(
                        update(_employees).where(_employees.c.id == row["id"]).values(**changes)
                    )
                stats["employees_encrypted"] += encrypted_fields
                stats["employee_indexes_updated"] += index_fields
            else:
                stats["rows_unchanged"] += 1

        if not dry_run:
            await session.commit()
        offset += len(rows)
        if len(rows) < batch_size:
            break
    return stats


async def backfill_bank_accounts(
    session: AsyncSession,
    *,
    batch_size: int = 250,
    dry_run: bool = False,
    company_id: uuid.UUID | None = None,
) -> dict[str, int]:
    stats = _empty_stats()
    offset = 0
    while True:
        stmt = select(_bank_accounts).order_by(_bank_accounts.c.id).limit(batch_size).offset(offset)
        if company_id is not None:
            stmt = stmt.join(_employees, _employees.c.id == _bank_accounts.c.employee_id).where(
                _employees.c.company_id == company_id
            )
        rows = list((await session.execute(stmt)).mappings().all())
        if not rows:
            break

        for row in rows:
            stats["bank_accounts_scanned"] += 1
            changes: dict[str, Any] = {}
            for field_name in BANK_PII_FIELDS:
                stored = row[field_name]
                if stored is not None and not is_encrypted_value(stored):
                    changes[field_name] = encrypt_value(stored)
            if changes:
                if not dry_run:
                    await session.execute(
                        update(_bank_accounts).where(_bank_accounts.c.id == row["id"]).values(**changes)
                    )
                stats["bank_values_encrypted"] += len(changes)
            else:
                stats["rows_unchanged"] += 1

        if not dry_run:
            await session.commit()
        offset += len(rows)
        if len(rows) < batch_size:
            break
    return stats


def _merge_stats(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


async def backfill_encrypted_pii(
    session: AsyncSession,
    *,
    batch_size: int = 250,
    dry_run: bool = False,
    company_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Backfill both employee and bank tables using an existing session."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    stats = _empty_stats()
    _merge_stats(
        stats,
        await backfill_employees(
            session, batch_size=batch_size, dry_run=dry_run, company_id=company_id
        ),
    )
    _merge_stats(
        stats,
        await backfill_bank_accounts(
            session, batch_size=batch_size, dry_run=dry_run, company_id=company_id
        ),
    )
    return stats


async def run_backfill(
    *, batch_size: int = 250, dry_run: bool = False, company_id: uuid.UUID | None = None
) -> dict[str, int]:
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return await backfill_encrypted_pii(
            session, batch_size=batch_size, dry_run=dry_run, company_id=company_id
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--dry-run", action="store_true", help="Count changes without writing them")
    parser.add_argument("--company-id", type=uuid.UUID, default=None)
    args = parser.parse_args()
    stats = asyncio.run(
        run_backfill(batch_size=args.batch_size, dry_run=args.dry_run, company_id=args.company_id)
    )
    # Aggregate counts only; plaintext/ciphertext identifiers are never printed.
    print("Encrypted PII backfill completed" + (" (dry run)" if args.dry_run else ""))
    for key in sorted(stats):
        print(f"{key}={stats[key]}")


if __name__ == "__main__":
    main()
