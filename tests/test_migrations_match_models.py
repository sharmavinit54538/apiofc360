"""Test that Alembic migrations match SQLAlchemy Base.metadata (zero diffs).

Runs `alembic.autogenerate.compare_metadata` against target PostgreSQL DB.
Skips if DATABASE_URL is not configured in environment.
"""

from __future__ import annotations

import os
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.base import Base
import app.models  # Import all models to register with Base.metadata


def _compare_server_default(context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_metadata_default):
    from sqlalchemy.sql.sqltypes import JSON, Enum
    if isinstance(metadata_column.type, JSON):
        return False
    if isinstance(metadata_column.type, Enum) or 'enum' in str(metadata_column.type).lower() or metadata_column.name == 'role':
        return False
    return None


@pytest.mark.asyncio
async def test_migrations_match_models():
    """Assert zero diffs between Base.metadata and upgraded PostgreSQL database."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL environment variable is not set; skipping live DB schema check.")

    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)

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

    assert len(diffs) == 0, f"Detected {len(diffs)} schema differences between models and database: {diffs}"
