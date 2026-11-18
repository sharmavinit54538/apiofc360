"""Read-only schema and dependency admission checks. Never performs DDL."""
import asyncio
from functools import lru_cache
from pathlib import Path
from sqlalchemy import text
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import settings


@lru_cache(maxsize=1)
def expected_revisions():
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def check_schema(engine):
    async with engine.connect() as connection:
        revisions = set((await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars())
    if revisions != expected_revisions():
        raise RuntimeError("Database migrations must be applied before release")


async def readiness(engine):
    checks = {"database": False, "schema": False, "redis": False}
    try:
        await asyncio.wait_for(check_schema(engine), timeout=5)
        checks.update(database=True, schema=True)
    except Exception:
        pass
    try:
        from app.core.redis_client import redis_client
        if redis_client.is_connected and redis_client._redis:
            checks["redis"] = bool(await asyncio.wait_for(redis_client._redis.ping(), timeout=2))
    except Exception:
        pass
    required = [checks["database"], checks["schema"]]
    if settings.is_production or settings.USE_CELERY:
        required.append(checks["redis"])
    return {"ready": all(required), **checks}
