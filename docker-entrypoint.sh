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

# Pull Ollama models if AI_AUTO_PULL_MODELS is enabled
if [ "$AI_AUTO_PULL_MODELS" = "true" ] && [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "[Entrypoint] AI_AUTO_PULL_MODELS=true - pulling Ollama models..."
    OLLAMA_HOST="${OLLAMA_BASE_URL:-http://ollama:11434}"
    DEFAULT_MODEL="${OLLAMA_DEFAULT_MODEL:-llama3.2:3b}"
    EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text:latest}"

    # Wait for Ollama to be ready
    echo "[Entrypoint] Waiting for Ollama at $OLLAMA_HOST..."
    for i in $(seq 1 30); do
        if curl -sf "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
            echo "[Entrypoint] Ollama is reachable."
            break
        fi
        echo "[Entrypoint] Waiting for Ollama... ($i/30)"
        sleep 2
    done

    # Pull default chat model
    echo "[Entrypoint] Pulling model: $DEFAULT_MODEL"
    curl -s -X POST "$OLLAMA_HOST/api/pull" -H "Content-Type: application/json" -d "{\"name\":\"$DEFAULT_MODEL\"}" | \
        jq -r 'select(.status) | .status' 2>/dev/null || true
    echo "[Entrypoint] Model pull initiated for $DEFAULT_MODEL (continues in background)."

    # Pull embedding model
    echo "[Entrypoint] Pulling embedding model: $EMBEDDING_MODEL"
    curl -s -X POST "$OLLAMA_HOST/api/pull" -H "Content-Type: application/json" -d "{\"name\":\"$EMBEDDING_MODEL\"}" | \
        jq -r 'select(.status) | .status' 2>/dev/null || true
    echo "[Entrypoint] Model pull initiated for $EMBEDDING_MODEL (continues in background)."
fi

# Execute the container's main command
exec "$@"
