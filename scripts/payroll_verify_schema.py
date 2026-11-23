"""Read-only proof of the migrated disposable payroll database."""
import asyncio
import json
import os
from pathlib import Path

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory


async def main():
    url = os.environ["PAYROLL_POSTGRES_TEST_URL"]
    if ":55441/payroll_verify_" not in url or "@127.0.0.1:" not in url:
        raise RuntimeError("Expected the isolated verification cluster")
    connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        result = {
            "identity": dict(await connection.fetchrow("SELECT current_database(), current_user, inet_server_port()")),
            "revisions": [row[0] for row in await connection.fetch("SELECT version_num FROM alembic_version")],
            "columns": [dict(row) for row in await connection.fetch(
                "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='employees' AND "
                "column_name IN ('is_pf_eligible','pf_membership_active','is_eps_eligible',"
                "'pf_higher_wage_opted','eps_higher_wage_opted','pf_wage_ceiling_applicable') ORDER BY column_name")],
        }
        scripts = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")))
        assert len(result["revisions"]) == 1, result
        lineage = {item.revision for item in scripts.iterate_revisions(result["revisions"][0], "base")}
        assert "e1f2a3b4c5d6" in lineage, result
        assert len(result["columns"]) == 6, result
        assert all(row["is_nullable"] == "NO" and row["data_type"] == "boolean" for row in result["columns"])
        print(json.dumps(result, indent=2))
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
