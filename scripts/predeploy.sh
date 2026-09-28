#!/usr/bin/env bash
set -euo pipefail

# Elevate privileges if not already running as root
if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi

cd /root/apiofc360

VENV="/root/apiofc360/venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# Check if virtualenv or pip is missing or broken
if [ ! -x "$PIP" ] || ! "$PIP" --version >/dev/null 2>&1; then
  echo "[Deploy] Virtual environment missing or broken (pip missing). Recreating virtualenv..."
  rm -rf "$VENV"

  # Ensure python3-venv / ensurepip is available before venv creation
  if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c "import ensurepip" >/dev/null 2>&1; then
    echo "[Deploy] python3-venv or ensurepip missing. Installing system packages..."
    SUDO=""
    if [ "$(id -u)" -ne 0 ]; then
      SUDO="sudo"
    fi
    export DEBIAN_FRONTEND=noninteractive

    $SUDO apt-get update -y

    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "")
    INSTALLED=0
    if [ -n "$PY_VER" ]; then
      if $SUDO apt-get install -y "python${PY_VER}-venv" python3-pip; then
        INSTALLED=1
      fi
    fi
    if [ "$INSTALLED" -eq 0 ]; then
      $SUDO apt-get install -y python3-venv python3-pip
    fi
  fi

  if ! python3 -m venv "$VENV"; then
    echo "[Deploy] ERROR: venv creation failed at $VENV!"
    exit 1
  fi

  if [ ! -x "$PIP" ]; then
    "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
  fi

  if [ ! -x "$PIP" ] || ! "$PIP" --version >/dev/null 2>&1; then
    echo "[Deploy] ERROR: pip verification failed in venv ($PIP is missing or broken)!"
    exit 1
  fi
  echo "[Deploy] Virtual environment created and verified successfully."
fi

# 1. Upgrade pip
echo "[Deploy] Upgrading pip..."
"$PIP" install --upgrade pip

# 2. Install dependencies
echo "[Deploy] Installing dependencies from requirements.txt..."
"$PIP" install -r requirements.txt

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
