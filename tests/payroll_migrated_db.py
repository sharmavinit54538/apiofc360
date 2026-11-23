"""Optional migrated PostgreSQL fixture; never creates application tables."""
from contextlib import asynccontextmanager
import os
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


async def seed_payroll_actor(session, company_id):
    """Persist the authenticated actor used by FK-backed audit/filing writes."""
    from app.models.user import User, UserRole
    actor_id = uuid.uuid4()
    session.add(User(id=actor_id, company_id=company_id, name="Payroll Test Admin",
                     email=f"{actor_id.hex}@example.test", phone=actor_id.hex[:10],
                     password_hash="unused-test-credential", role=UserRole.HR_ADMIN,
                     account_status="ACTIVE", is_active=True, is_verified=True))
    await session.commit()
    return actor_id


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
            scripts = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")))
            lineage = {item.revision for item in scripts.iterate_revisions(revision, "base")}
            assert "e1f2a3b4c5d6" in lineage, "Apply the PF/EPS migration before testing"
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False, autoflush=False,
                                        join_transaction_mode="create_savepoint") as session:
                    yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
