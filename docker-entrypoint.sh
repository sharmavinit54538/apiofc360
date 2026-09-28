#!/bin/sh
set -e

# If running as root (UID 0), ensure upload directories exist, fix ownership, and drop privileges to appuser
if [ "$(id -u)" = "0" ]; then
    echo "[Entrypoint] Running as root: creating /app/uploads and required subdirectories..."
    mkdir -p /app/uploads/onboarding \
             /app/uploads/qrcodes \
             /app/uploads/connect \
             /app/uploads/helpdesk \
             /app/uploads/face_attendance \
             /app/uploads/logos \
             /app/uploads/documents

    echo "[Entrypoint] Setting ownership of /app/uploads to appuser (10001:10001)..."
    chown -R 10001:10001 /app/uploads

    echo "[Entrypoint] Dropping privileges and re-executing entrypoint as appuser..."
    exec gosu appuser "$0" "$@"
fi

# Run database migrations ONLY for the API container (skips celery worker to avoid DB locks)
if [ "$RUN_MIGRATIONS" = "true" ] || [ "$1" = "uvicorn" ]; then
    echo "[Entrypoint] Verifying database connectivity before migrations..."
    python -c "
import asyncio, sys
from app.db.database import get_asyncpg_connection

async def check_db():
    for attempt in range(1, 16):
        try:
            conn = await get_asyncpg_connection()
            await conn.close()
            print(f'[Entrypoint] Database connectivity confirmed on attempt {attempt}/15.')
            return 0
        except Exception as err:
            print(f'[Entrypoint] Waiting for database readiness (attempt {attempt}/15)... ({err})')
            await asyncio.sleep(2)
    print('[Entrypoint] ERROR: Database connection timed out after 15 attempts.')
    return 1

sys.exit(asyncio.run(check_db()))
"

    if [ -f "scripts/migrate_face_attendance.py" ]; then
        echo "[Entrypoint] Ensuring face attendance schema columns..."
        python scripts/migrate_face_attendance.py || true
    fi

    if [ -f "alembic.ini" ]; then
        echo "[Entrypoint] Acquiring advisory lock for database migrations..."
        # Use Postgres advisory lock to prevent concurrent migration races
        # when multiple API replicas start simultaneously.
        # Lock key 483921747 is an arbitrary fixed integer.
        python -c "
import asyncio, sys, subprocess
from app.db.database import get_asyncpg_connection

async def run_migrations_with_lock():
    conn = await get_asyncpg_connection()
    try:
        print('[Entrypoint] Waiting for migration lock (pg_advisory_lock)...')
        await conn.execute('SELECT pg_advisory_lock(483921747)')
        print('[Entrypoint] Lock acquired.')

        # Pre-flight check: ensure no multiple heads / branch divergence
        print('[Entrypoint] Pre-flight: checking for multiple Alembic heads...')
        heads_check = subprocess.run(
            ['alembic', 'heads', '--resolve-dependencies'],
            capture_output=True,
            text=True
        )
        if heads_check.returncode != 0:
            print(f'[Entrypoint] ERROR: Failed to inspect alembic heads:\n{heads_check.stderr}')
            return heads_check.returncode

        head_lines = [line.strip() for line in heads_check.stdout.strip().splitlines() if line.strip()]
        if len(head_lines) > 1:
            print('[Entrypoint] FATAL: Multiple Alembic heads detected! Migration history has diverged:')
            for h in head_lines:
                print(f'  - {h}')
            print('[Entrypoint] Aborting deploy. Merge migration branches using `alembic merge heads` before deploying.')
            return 1

        active_head = head_lines[0] if head_lines else 'None'
        print(f'[Entrypoint] Single head verified ({active_head}).')

        # Pre-flight check: verify current DB revision exists in codebase
        print('[Entrypoint] Pre-flight: checking database revision against local migrations...')
        table_check = await conn.fetchval(
            "SELECT to_regclass('public.alembic_version')"
        )
        if table_check:
            db_rows = await conn.fetch("SELECT version_num FROM alembic_version")
            db_revisions = [r['version_num'] for r in db_rows if r['version_num']]
            if db_revisions:
                from alembic.config import Config
                from alembic.script import ScriptDirectory
                from alembic.util.exc import CommandError

                alembic_cfg = Config('alembic.ini')
                script_dir = ScriptDirectory.from_config(alembic_cfg)
                code_heads = script_dir.get_heads()

                for db_rev in db_revisions:
                    try:
                        script_dir.get_revision(db_rev)
                    except CommandError:
                        heads_str = ', '.join(code_heads) if code_heads else 'None'
                        print('[Entrypoint] ERROR: Database revision does not exist in local migration history!')
                        print(f'[Entrypoint]   - Current DB revision : {db_rev}')
                        print(f'[Entrypoint]   - Codebase head(s)    : {heads_str}')
                        print('[Entrypoint]   - Hint: DB was migrated by a different codebase version; restore the missing migration file or ask the maintainer to stamp the DB')
                        return 1

        print(f'[Entrypoint] Database revision verified – running alembic upgrade head...')
        result = subprocess.run(['alembic', 'upgrade', 'head'], capture_output=False)
        if result.returncode != 0:
            print(f'[Entrypoint] ERROR: alembic upgrade failed with exit code {result.returncode}')
            return result.returncode
        print('[Entrypoint] Database migrations completed successfully.')
        return 0
    finally:
        await conn.execute('SELECT pg_advisory_unlock(483921747)')
        await conn.close()
        print('[Entrypoint] Migration lock released.')

sys.exit(asyncio.run(run_migrations_with_lock()))
"
    fi
fi

# Execute the container's main command
exec "$@"
