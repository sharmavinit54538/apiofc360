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


async def inspect_schema_drift(engine) -> dict:
    """Compare Alembic revision and live ORM table/column presence cleanly (read-only)."""
    import app.models  # noqa: F401
    from app.db.base import Base

    async with engine.connect() as connection:
        revisions = set(
            (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars()
        )
        rows = (
            await connection.execute(
                text(
                    "SELECT table_name, column_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        ).fetchall()

    db_columns: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        db_columns.setdefault(table_name, set()).add(column_name)

    missing_tables = 0
    missing_columns = 0
    for table_name, table in Base.metadata.tables.items():
        if table_name not in db_columns:
            missing_tables += 1
            continue
        existing = db_columns[table_name]
        for col in table.columns:
            if col.name not in existing:
                missing_columns += 1

    expected = expected_revisions()
    return {
        "revision_match": revisions == expected,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "schema_drift": (revisions != expected) or missing_tables > 0 or missing_columns > 0,
    }


async def check_schema(engine):
    report = await inspect_schema_drift(engine)
    if not report["revision_match"]:
        raise RuntimeError("Database migrations must be applied before release")
    if report["missing_tables"] > 0 or report["missing_columns"] > 0:
        raise RuntimeError(
            f"Database schema drift detected (missing_tables={report['missing_tables']}, missing_columns={report['missing_columns']})"
        )


async def readiness(engine):
    checks = {"database": False, "schema": False, "redis": False}
    drift_summary = {"schema_drift": True, "missing_tables": 0, "missing_columns": 0}
    try:
        drift_summary = await asyncio.wait_for(inspect_schema_drift(engine), timeout=5)
        checks["database"] = True
        checks["schema"] = not drift_summary["schema_drift"]
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
    return {
        "ready": all(required),
        **checks,
        "schema_drift": drift_summary["schema_drift"],
    }
