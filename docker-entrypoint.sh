#!/bin/sh
set -e

# Run database migrations ONLY for the API container (skips celery worker to avoid DB locks)
if [ "$RUN_MIGRATIONS" = "true" ] || [ "$1" = "uvicorn" ]; then
    if [ -f "alembic.ini" ]; then
        echo "[Entrypoint] Running database migrations (alembic upgrade head)..."
        alembic upgrade head || echo "[Entrypoint] Warning: Migration check encountered issue, continuing startup..."
    fi
fi

# Execute the container's main command
exec "$@"
