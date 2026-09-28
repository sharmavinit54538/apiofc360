#!/usr/bin/env python3
"""Execute database migrations with PostgreSQL advisory lock and pre-flight checks."""

import asyncio
import os
import subprocess
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.getcwd())

from app.db.database import get_asyncpg_connection

ADVISORY_LOCK_ID = 483921747


async def run_migrations_with_lock() -> int:
    print("[Entrypoint] Connecting to database for migration execution...")
    conn = await get_asyncpg_connection()
    try:
        print(f"[Entrypoint] Waiting for migration lock (pg_advisory_lock {ADVISORY_LOCK_ID})...")
        await conn.execute("SELECT pg_advisory_lock(483921747)")
        print("[Entrypoint] Lock acquired.")

        # Pre-flight check: ensure no multiple heads / branch divergence
        print("[Entrypoint] Pre-flight: checking for multiple Alembic heads...")
        heads_check = subprocess.run(
            ["alembic", "heads", "--resolve-dependencies"],
            capture_output=True,
            text=True,
        )
        if heads_check.returncode != 0:
            print(f"[Entrypoint] ERROR: Failed to inspect alembic heads:\n{heads_check.stderr}")
            return heads_check.returncode

        head_lines = [
            line.strip()
            for line in heads_check.stdout.strip().splitlines()
            if line.strip()
        ]
        if len(head_lines) > 1:
            print("[Entrypoint] FATAL: Multiple Alembic heads detected! Migration history has diverged:")
            for h in head_lines:
                print(f"  - {h}")
            print("[Entrypoint] Aborting deploy. Merge migration branches using `alembic merge heads` before deploying.")
            return 1

        active_head = head_lines[0] if head_lines else "None"
        print(f"[Entrypoint] Single head verified ({active_head}).")

        # Pre-flight check: verify current DB revision exists in codebase
        print("[Entrypoint] Pre-flight: checking database revision against local migrations...")
        table_check = await conn.fetchval(
            "SELECT to_regclass('public.alembic_version')"
        )
        if table_check:
            db_rows = await conn.fetch("SELECT version_num FROM alembic_version")
            db_revisions = [r["version_num"] for r in db_rows if r["version_num"]]
            if db_revisions:
                from alembic.config import Config
                from alembic.script import ScriptDirectory
                from alembic.util.exc import CommandError

                alembic_cfg = Config("alembic.ini")
                script_dir = ScriptDirectory.from_config(alembic_cfg)
                code_heads = script_dir.get_heads()

                for db_rev in db_revisions:
                    try:
                        script_dir.get_revision(db_rev)
                    except CommandError:
                        heads_str = ", ".join(code_heads) if code_heads else "None"
                        print("[Entrypoint] ERROR: Database revision does not exist in local migration history!")
                        print(f"[Entrypoint]   - Current DB revision : {db_rev}")
                        print(f"[Entrypoint]   - Codebase head(s)    : {heads_str}")
                        print(
                            "[Entrypoint]   - Hint: DB was migrated by a different codebase version; "
                            "restore the missing migration file or ask the maintainer to stamp the DB"
                        )
                        return 1

        print("[Entrypoint] Database revision verified – running alembic upgrade head...")
        result = subprocess.run(["alembic", "upgrade", "head"])
        if result.returncode != 0:
            print(f"[Entrypoint] ERROR: alembic upgrade failed with exit code {result.returncode}")
            return result.returncode

        print("[Entrypoint] Database migrations completed successfully.")
        return 0
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock(483921747)")
            print("[Entrypoint] Migration lock released.")
        except Exception as exc:
            print(f"[Entrypoint] Warning: Failed to release advisory lock: {exc}")
        try:
            await conn.close()
        except Exception:
            pass


def main() -> int:
    return asyncio.run(run_migrations_with_lock())


if __name__ == "__main__":
    sys.exit(main())
