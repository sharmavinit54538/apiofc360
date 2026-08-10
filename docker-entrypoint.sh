#!/bin/sh
set -e

# Run database migrations if alembic is available
if [ -f "alembic.ini" ]; then
    echo "[Entrypoint] Running database migrations (alembic upgrade head)..."
    alembic upgrade head || echo "[Entrypoint] Warning: Migration check encountered issue, continuing startup..."
fi

# Execute the container's main command
exec "$@"
