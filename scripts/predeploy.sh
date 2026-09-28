#!/usr/bin/env bash
set -euo pipefail

# Elevate privileges if not already running as root
if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi

cd /root/apiofc360

VENV="/root/apiofc360/venv"
PY="$VENV/bin/python"

# Check if virtualenv or pip is missing or broken
if [ ! -f "$PY" ] || ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "[Deploy] Virtual environment missing or broken (pip missing). Recreating virtualenv..."
  rm -rf "$VENV"
  if ! python3 -m venv "$VENV"; then
    echo "[Deploy] ERROR: venv creation failed! python3-venv install karo: sudo apt-get install -y python3-venv"
    exit 1
  fi
  "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
  if ! "$PY" -m pip --version >/dev/null 2>&1; then
    echo "[Deploy] ERROR: pip missing in venv! python3-venv install karo: sudo apt-get install -y python3-venv"
    exit 1
  fi
fi

# 1. Upgrade pip
echo "[Deploy] Upgrading pip..."
"$PY" -m pip install --upgrade pip

# 2. Install dependencies
echo "[Deploy] Installing dependencies from requirements.txt..."
"$PY" -m pip install -r requirements.txt

# 3. Compile Python syntax across app/
echo "[Deploy] Compiling Python syntax across app/..."
"$PY" -m compileall -q app

# 4. Validate settings configuration without logging sensitive variable values
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
