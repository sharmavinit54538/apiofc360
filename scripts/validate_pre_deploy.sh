#!/usr/bin/env bash
# ==============================================================================
# Pre-deploy syntax compilation and settings validation script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${APP_DIR}"

echo "[Deploy] Running pre-deploy syntax compilation and settings validation..."

# Determine Python interpreter inside virtual environment
VENV_DIR="${APP_DIR}/venv"
if [ -f "${VENV_DIR}/bin/python" ]; then
  PY="${VENV_DIR}/bin/python"
elif [ -f "${VENV_DIR}/Scripts/python.exe" ]; then
  PY="${VENV_DIR}/Scripts/python.exe"
else
  PY="${VENV_DIR}/bin/python"
fi

# 1. Create virtualenv if it does not exist
if [ ! -d "${VENV_DIR}" ] || [ ! -f "${PY}" ]; then
  echo "[Deploy] Virtual environment not found at ${VENV_DIR}. Creating virtualenv..."
  if python3 -c 'import sys' >/dev/null 2>&1; then
    SYS_PY="python3"
  elif python -c 'import sys' >/dev/null 2>&1; then
    SYS_PY="python"
  else
    SYS_PY="python3"
  fi
  "${SYS_PY}" -m venv "${VENV_DIR}"
  if [ -f "${VENV_DIR}/Scripts/python.exe" ]; then
    PY="${VENV_DIR}/Scripts/python.exe"
  else
    PY="${VENV_DIR}/bin/python"
  fi
fi

# 2. Install dependencies if not already present
if ! "${PY}" -c "import pydantic, pydantic_settings" 2>/dev/null; then
  echo "[Deploy] Installing dependencies from requirements.txt..."
  "${PY}" -m pip install -r requirements.txt || "${PY}" -m pip install pydantic pydantic-settings
else
  echo "[Deploy] Required dependencies already present in virtualenv."
fi

# 3. Compile Python syntax across app directory
echo "[Deploy] Compiling Python syntax across app/..."
"${PY}" -m compileall -q app

# 4. Validate settings without leaking sensitive environment variables
echo "[Deploy] Validating settings configuration..."
"${PY}" -c "
import sys
try:
    from app.core.config import settings
    print('[Deploy] settings OK')
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
