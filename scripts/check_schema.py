#!/usr/bin/env python3
"""Read-only schema validator comparing SQLAlchemy models against PostgreSQL information_schema.

Usage:
    python scripts/check_schema.py
    DATABASE_URL="postgresql+asyncpg://..." python scripts/check_schema.py

Safe to run against production databases (performs read-only SELECT queries).
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.db.base import Base
import app.models  # Ensures all models are registered on Base.metadata


async def check_schema(db_url: str | None = None) -> int:
    """Compare Base.metadata with information_schema in target PostgreSQL database."""
    database_url = db_url or os.getenv("DATABASE_URL") or settings.DATABASE_URL
    # Ensure asyncpg dialect
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"[Schema Check] Connecting to database (masked URL: {database_url.split('@')[-1] if '@' in database_url else 'local'})...")

    engine = create_async_engine(database_url, echo=False)

    try:
        async with engine.connect() as conn:
            # 1. Fetch all public tables from information_schema
            tables_query = text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
            )
            res = await conn.execute(tables_query)
            existing_tables = {row[0] for row in res.fetchall()}

            # 2. Fetch all public columns from information_schema
            cols_query = text(
                "SELECT table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public';"
            )
            res = await conn.execute(cols_query)
            db_columns: dict[str, set[str]] = {}
            for table_name, column_name, _, _ in res.fetchall():
                db_columns.setdefault(table_name, set()).add(column_name)

    except Exception as exc:
        print(f"[Schema Check] ERROR: Could not connect to or query database: {exc}")
        await engine.dispose()
        return 1

    await engine.dispose()

    # 3. Compare with Base.metadata
    metadata_tables = Base.metadata.tables
    print(f"[Schema Check] Comparing {len(metadata_tables)} models in Base.metadata against {len(existing_tables)} database tables...")

    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}
    matched_tables_count = 0

    for table_name, table in metadata_tables.items():
        if table_name not in existing_tables:
            missing_tables.append(table_name)
            continue

        matched_tables_count += 1
        existing_cols = db_columns.get(table_name, set())
        for column in table.columns:
            if column.name not in existing_cols:
                missing_columns.setdefault(table_name, []).append(column.name)

    # 4. Display results
    print("=" * 60)
    print("SCHEMA VERIFICATION REPORT")
    print("=" * 60)
    print(f"Total Models in Codebase:     {len(metadata_tables)}")
    print(f"Tables Found in Database:     {len(existing_tables)}")
    print(f"Matched Models with DB Table: {matched_tables_count}")

    has_errors = False

    if missing_tables:
        has_errors = True
        print(f"\n[!] MISSING TABLES ({len(missing_tables)}):")
        for tbl in sorted(missing_tables):
            print(f"  - {tbl}")

    if missing_columns:
        has_errors = True
        total_missing_cols = sum(len(cols) for cols in missing_columns.values())
        print(f"\n[!] MISSING COLUMNS ({total_missing_cols} across {len(missing_columns)} tables):")
        for tbl, cols in sorted(missing_columns.items()):
            print(f"  Table '{tbl}':")
            for col in sorted(cols):
                print(f"    - {col}")

    if not has_errors:
        print("\n[OK] SUCCESS: All model tables and columns exist in the database.")
        print("=" * 60)
        return 0
    else:
        print("\n[X] FAILURE: Schema drift detected between models and database.")
        print("=" * 60)
        return 1


def main() -> None:
    target_url = sys.argv[1] if len(sys.argv) > 1 else None
    exit_code = asyncio.run(check_schema(target_url))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
