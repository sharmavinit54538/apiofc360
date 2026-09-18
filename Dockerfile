# syntax=docker/dockerfile:1
# Production multi-stage Dockerfile for FastAPI HRMS backend (apiofc360)

# ==============================================================================
# Stage 1: Builder (compiler toolchains, wheel prebuilt provisioning, and assembly)
# ==============================================================================
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=4 \
    DLIB_NO_GUI_SUPPORT=1 \
    DLIB_USE_CUDA=0

WORKDIR /build

# Install compiler tools and development libraries needed for C-extensions:
# libpq-dev (PostgreSQL), build-essential (gcc/g++), cmake, libopenblas-dev (BLAS acceleration)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated virtual environment so all compiled packages can be cleanly copied to runner
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade core package management tools
RUN pip install --upgrade pip setuptools wheel

# 1. Provision dlib using prebuilt binary wheel (or optimized parallel compile fallback)
# This step is isolated and runs before general requirements to ensure maximum layer caching
COPY scripts/install_dlib.py /build/scripts/install_dlib.py
RUN --mount=type=cache,target=/root/.cache/pip \
    python /build/scripts/install_dlib.py

# 2. Copy requirements.txt and install all application dependencies
# Layer caching ensures this is ONLY re-executed when requirements.txt changes
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Verify the virtual environment passes dependency consistency checks
RUN pip check && python -c "import dlib, face_recognition, numpy; print('[Builder] Verified dlib and face_recognition import successfully!')"


# ==============================================================================
# Stage 2: Final Production Runtime Image
# ==============================================================================
FROM python:3.11-slim-bookworm AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install ONLY runtime shared libraries (no compilers, no cmake, no dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgl1 \
    libglib2.0-0 \
    libopenblas0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy assembled virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy entrypoint script and ensure executable permissions
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Copy application source code (done AFTER dependencies for optimal Docker layer reuse)
COPY . /app

# Create non-root system user and prepare uploads directory for security
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/uploads && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Smoke test imports in the final runtime container
RUN python -c "import dlib, face_recognition, cv2, numpy, fastapi; print('[Runtime] Smoke test PASSED: All biometrics and web modules load cleanly.')"

# Container healthcheck probe
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Default entrypoint and command
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
