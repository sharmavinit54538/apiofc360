"""Optional migrated PostgreSQL fixture; never creates application tables."""
from contextlib import asynccontextmanager
import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


@asynccontextmanager
async def migrated_session():
    raw = os.environ["PAYROLL_POSTGRES_TEST_URL"]
    url = make_url(raw)
    if (os.environ.get("PAYROLL_TEST_DISPOSABLE") != "1"
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").startswith("payroll_verify_")):
        raise RuntimeError("An explicitly disposable local payroll database is required")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "e1f2a3b4c5d6", "Run Alembic upgrade head before testing"
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False, autoflush=False,
                                        join_transaction_mode="create_savepoint") as session:
                    yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
