import asyncio
import os
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db.base import Base
import app.models

def _compare_server_default(context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_metadata_default):
    from sqlalchemy.sql.sqltypes import JSON, Enum
    if isinstance(metadata_column.type, JSON):
        return False
    if isinstance(metadata_column.type, Enum) or 'enum' in str(metadata_column.type).lower() or metadata_column.name == 'role':
        return False
    return None

async def check():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    def _sync_compare(conn):
        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "compare_server_default": _compare_server_default,
            },
        )
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        diffs = await conn.run_sync(_sync_compare)
    await engine.dispose()

    print(f"Total diffs against current DB: {len(diffs)}")
    for d in diffs:
        print("  -", d)

if __name__ == "__main__":
    asyncio.run(check())
