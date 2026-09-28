#!/bin/sh
set -e

# If running as root (UID 0), ensure upload directories exist, fix ownership, and drop privileges to appuser
if [ "$(id -u)" = "0" ]; then
    echo "[Entrypoint] Running as root: creating /app/uploads and subdirectories..."
    mkdir -p /app/uploads/face_attendance \
             /app/uploads/onboarding \
             /app/uploads/qrcodes \
             /app/uploads/connect \
             /app/uploads/helpdesk \
             /app/uploads/logos \
             /app/uploads/documents

    echo "[Entrypoint] Setting ownership of /app/uploads and subdirectories to appuser (10001:10001)..."
    chown -R appuser:appuser /app/uploads
    chmod -R 775 /app/uploads

    echo "[Entrypoint] Dropping privileges and re-executing entrypoint as appuser..."
    exec gosu appuser "$0" "$@"
fi

# Run database migrations ONLY for the API container (skips celery worker to avoid DB locks)
if [ "$RUN_MIGRATIONS" = "true" ] || [ "$1" = "uvicorn" ]; then
    echo "[Entrypoint] Verifying database connectivity before migrations..."
    python scripts/wait_for_db.py

    if [ -f "scripts/migrate_face_attendance.py" ]; then
        echo "[Entrypoint] Ensuring face attendance schema columns..."
        python scripts/migrate_face_attendance.py || true
    fi

    if [ -f "alembic.ini" ]; then
        echo "[Entrypoint] Acquiring advisory lock and running migrations..."
        python scripts/run_migrations.py
    fi
fi

# Execute the container's main command
exec "$@"
