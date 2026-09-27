#!/bin/sh
set -e

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

    mkdir -p /app/uploads/face_attendance 2>/dev/null || true

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
        print('[Entrypoint] Lock acquired – running alembic upgrade heads...')
        result = subprocess.run(['alembic', 'upgrade', 'heads'], capture_output=False)
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
