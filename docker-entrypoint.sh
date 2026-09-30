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

# Run database migrations only for the API container
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "[Entrypoint] Running database migrations: alembic upgrade head..."
    alembic upgrade head || {
        echo "[Entrypoint] FATAL: Database migration failed. Aborting startup."
        exit 1
    }
fi

# Execute the container's main command
exec "$@"
