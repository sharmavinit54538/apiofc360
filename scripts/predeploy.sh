#!/usr/bin/env bash
set -euo pipefail

# Elevate privileges if not already running as root
if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi

cd /root/apiofc360

VENV_DIR="/root/apiofc360/venv"
PY="/root/apiofc360/venv/bin/python"

# Create virtual environment if it does not exist
if [ ! -d "$VENV_DIR" ] || [ ! -f "$PY" ]; then
  echo "[Deploy] Virtual environment not found at $VENV_DIR. Creating virtualenv..."
  python3 -m venv "$VENV_DIR"
fi

# 1. Install dependencies
echo "[Deploy] Installing dependencies from requirements.txt..."
"$PY" -m pip install -r requirements.txt

# 2. Compile Python syntax
echo "[Deploy] Compiling Python syntax across app/..."
"$PY" -m compileall -q app

# 3. Validate settings configuration without logging sensitive variable values
echo "[Deploy] Validating settings configuration..."
"$PY" -c "
import sys
try:
    from app.core.config import settings
    print('settings OK')
except Exception as exc:
    errs = getattr(exc, 'errors', None)
    if callable(errs):
        print('[Deploy] ERROR: Settings validation failed. Missing or invalid required environment variables:')
        for e in errs():
            loc = ' -> '.join(str(p) for p in e.get('loc', []))
            msg = e.get('msg', '')
            print(f'  - {loc}: {msg}')
    else:
        print(f'[Deploy] ERROR: Settings validation failed: {type(exc).__name__}: {exc}')
    sys.exit(1)
"
