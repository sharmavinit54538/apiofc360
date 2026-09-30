#!/usr/bin/env python3
"""Print schema diff between Alembic MigrationContext and SQLAlchemy Base.metadata.

Usage:
    python scripts/schema_diff.py
    DATABASE_URL="postgresql+asyncpg://..." python scripts/schema_diff.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.db.base import Base
import app.models  # Import all models as in alembic/env.py
import importlib.util
_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic", "env.py"))
_spec = importlib.util.spec_from_file_location("alembic_env_module", _env_path)
_alembic_env = importlib.util.module_from_spec(_spec)
# Note: we don't execute the entire env.py because it triggers migrations.
# Instead, define or extract my_compare_server_default:
def my_compare_server_default(context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_metadata_default):
    from sqlalchemy.sql.sqltypes import JSON, Enum
    if isinstance(metadata_column.type, JSON):
        return False
    if isinstance(metadata_column.type, Enum) or 'enum' in str(metadata_column.type).lower() or metadata_column.name == 'role':
        return False
    return None



def format_diff_item(diff: Any) -> tuple[str, str]:
    """Return (table_name, formatted_diff_string) for a single diff item."""
    if isinstance(diff, list):
        # A list of column modifications for the same column
        # e.g. [('modify_type', ...), ('modify_default', ...)]
        table_name = "unknown"
        sub_diffs = []
        for sub in diff:
            t, s = format_single_diff(sub)
            if t != "unknown":
                table_name = t
            sub_diffs.append(s)
        return table_name, " | ".join(sub_diffs)
    else:
        return format_single_diff(diff)


def format_single_diff(diff: tuple) -> tuple[str, str]:
    diff_type = diff[0]
    if diff_type in ("add_table", "remove_table"):
        table = diff[1]
        tname = table.name if hasattr(table, "name") else str(table)
        return tname, f"{diff_type}: table {tname}"

    elif diff_type in ("add_column", "remove_column"):
        schema, tname, col = diff[1], diff[2], diff[3]
        col_type = str(getattr(col, "type", ""))
        nullable = getattr(col, "nullable", None)
        default = getattr(col, "server_default", None)
        extra = []
        if col_type:
            extra.append(f"type={col_type}")
        if nullable is not None:
            extra.append(f"nullable={nullable}")
        if default is not None:
            extra.append(f"default={default.arg if hasattr(default, 'arg') else default}")
        extra_str = f" ({', '.join(extra)})" if extra else ""
        return tname, f"{diff_type}: {tname}.{col.name}{extra_str}"

    elif diff_type == "modify_type":
        schema, tname, colname, metadata_info, old_type, new_type = diff[1:7]
        return tname, f"modify_type: {tname}.{colname}: DB has {old_type}, Model has {new_type}"

    elif diff_type == "modify_nullable":
        schema, tname, colname, metadata_info, old_nullable, new_nullable = diff[1:7]
        return tname, f"modify_nullable: {tname}.{colname}: DB nullable={old_nullable}, Model nullable={new_nullable}"

    elif diff_type == "modify_default":
        schema, tname, colname, metadata_info, old_default, new_default = diff[1:7]
        old_val = old_default.arg if hasattr(old_default, "arg") else old_default
        new_val = new_default.arg if hasattr(new_default, "arg") else new_default
        return tname, f"modify_default: {tname}.{colname}: DB default={old_val}, Model default={new_val}"

    elif diff_type in ("add_index", "remove_index"):
        idx = diff[1]
        tname = idx.table.name if hasattr(idx, "table") and idx.table is not None else "unknown"
        cols = ", ".join(c.name for c in idx.columns) if hasattr(idx, "columns") else ""
        return tname, f"{diff_type}: {idx.name} on {tname}({cols})"

    elif diff_type in ("add_fk", "remove_fk"):
        fk = diff[1]
        tname = fk.parent.name if hasattr(fk, "parent") and fk.parent is not None else "unknown"
        return tname, f"{diff_type}: {fk.name or 'unnamed_fk'} on {tname}"

    elif diff_type in ("add_constraint", "remove_constraint"):
        cons = diff[1]
        tname = cons.table.name if hasattr(cons, "table") and cons.table is not None else "unknown"
        cols = ", ".join(c.name for c in cons.columns) if hasattr(cons, "columns") else ""
        return tname, f"{diff_type}: {cons.name or 'unnamed_cons'} on {tname}({cols})"

    else:
        return "unknown", f"{diff_type}: {diff}"


async def run_diff() -> list[tuple[str, str]]:
    db_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)

    def _sync_compare(conn):
        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "compare_server_default": my_compare_server_default,
            },
        )
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        raw_diffs = await conn.run_sync(_sync_compare)

    await engine.dispose()

    formatted: list[tuple[str, str]] = []
    for item in raw_diffs:
        tname, desc = format_diff_item(item)
        formatted.append((tname, desc))

    return formatted


def main():
    diffs = asyncio.run(run_diff())
    by_table: dict[str, list[str]] = defaultdict(list)
    for tname, desc in diffs:
        by_table[tname].append(desc)

    lines = []
    lines.append(f"Total diffs detected: {len(diffs)} across {len(by_table)} tables/entities")
    lines.append("=" * 80)
    for tname in sorted(by_table.keys()):
        lines.append(f"Table [{tname}]:")
        for desc in sorted(by_table[tname]):
            lines.append(f"  - {desc}")
        lines.append("")

    output_content = "\n".join(lines)
    print(output_content)

    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "schema_diff.txt"))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_content + "\n")
    print(f"Diff output written to {output_path}")


if __name__ == "__main__":
    main()
