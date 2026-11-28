"""Main application entrypoint for FastAPI backend."""
# AI Workforce Planning endpoints active

import asyncio
import contextlib
import logging
import multiprocessing
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
try:
    from starlette.middleware.sessions import SessionMiddleware
    HAS_SESSION_MIDDLEWARE = True
except ImportError:
    HAS_SESSION_MIDDLEWARE = False
    SessionMiddleware = None

from sqlalchemy import text

# Performance instrumentation
from app.core.perf_instrumentation import (
    install_db_instrumentation,
    wrap_redis_client,
    start_lag_detector,
    stop_lag_detector_async,
    PerfHeadersMiddleware,
)

# Unified Routers - Single import for all v1 and v2 endpoints
from app.api.v1.router import v1_router
from app.api.v2.router import v2_router
from app.api.v2.scim_api import router as scim_v2_router

# Legacy public/unprefixed routers (keep separate for backward compatibility)
from app.api.careers import router as careers_router
from app.api.generate_api import router as generate_router
from app.api.v1.intelligence import router as intelligence_router
from app.api.settings import router as settings_api_router
from app.api.billing import router as billing_router
from app.api.payments import router as payments_router
from app.api.onboarding import router as onboarding_router
from app.api.hr_admin_onboarding import router as hr_admin_onboarding_router
from app.api.sidebar import router as sidebar_router
from app.routers.notifications import router as core_notifications_router
from app.api.departments import router as departments_router
from app.api.hr_interview_dashboard import router as hr_interview_dashboard_router
from app.api.file_downloads import router as file_downloads_router

from app.db.database import engine, get_db_session
from app.middleware.auth import get_current_user_claims
from app.core.config import settings
from app.core.exceptions import install_exception_handlers

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger = logging.getLogger("app.main")


async def init_db_with_retry(max_retries: int = 5, initial_delay: float = 1.0, backoff_factor: float = 2.0) -> bool:
    """Attempt database connection with exponential backoff retry logic."""
    import asyncio
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Initializing database connection (Attempt %d/%d)...", attempt, max_retries)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connectivity check SUCCESSFUL on attempt %d.", attempt)
            
            from app.core.readiness import check_schema
            await check_schema(engine)

            return True
        except Exception as e:
            if "postgres.railway.internal" in str(e):
                logger.error(
                    "DATABASE CONNECTIVITY CRITICAL ERROR: 'postgres.railway.internal' is unreachable. "
                    "You are using Railway's internal hostname on Render. Replace DATABASE_URL with Railway's Public / External URL."
                )
            else:
                logger.error("Database connection attempt %d/%d failed (%s)", attempt, max_retries, type(e).__name__)
                
            if attempt < max_retries:
                logger.info("Retrying database connection in %.1f seconds...", delay)
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error("Database connection failed after %d retries. Readiness will remain unavailable.", max_retries)
                return False


async def ensure_superadmin_provisioned():
    """Read-only startup validation; provisioning and recovery require the CLI."""
    from app.services.platform_owner import validate_platform_owner
    from app.db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await validate_platform_owner(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler with retry logic and graceful shutdown."""
    import asyncio
    logger.info("Starting up FastAPI application...")
    
    db_connected = await init_db_with_retry(max_retries=5, initial_delay=1.0, backoff_factor=2.0)
    if db_connected:
        # Install DB query instrumentation
        try:
            install_db_instrumentation(engine.sync_engine)
        except Exception as e:
            logger.warning("DB instrumentation install failed: %s", e)

        try:
            from app.core.field_encryption import FieldEncryptionError, configured_key_ids, validate_encryption_configuration
            enc_info = validate_encryption_configuration()
            logger.info(
                "Field encryption validated: active_key_id=%s | retained_key_ids=%s | keys=%d",
                enc_info["active_key_id"],
                enc_info["retained_key_ids"],
                enc_info["key_count"],
            )
            # Audit encrypted envelope key_ids present in database without decrypting or logging PII
            try:
                from sqlalchemy import text
                from app.db.database import AsyncSessionLocal
                active_ids = set(configured_key_ids())
                async with AsyncSessionLocal() as enc_session:
                    missing_keys: dict[str, int] = {}
                    for tbl, cols in (
                        ("employees", ("aadhaar_number", "pan_number", "uan_number", "passport_number", "voter_id")),
                        ("employee_bank_accounts", ("account_number", "ifsc_code")),
                    ):
                        for col in cols:
                            res = await enc_session.execute(
                                text(
                                    f"SELECT split_part({col}, ':', 3) AS key_id, COUNT(*) "
                                    f"FROM {tbl} WHERE {col} LIKE 'ofc360:v1:%' "
                                    f"GROUP BY split_part({col}, ':', 3)"
                                ).execution_options(tenant_safe=True)
                            )
                            for key_id, cnt in res.fetchall():
                                if key_id and key_id not in active_ids:
                                    missing_keys[key_id] = missing_keys.get(key_id, 0) + int(cnt)
                    if missing_keys:
                        logger.warning(
                            "Encryption key audit: %s historical encrypted field(s) use unconfigured key_id(s) %s. "
                            "Retain previous keys in FIELD_ENCRYPTION_KEY='new_key,old_key' during rotation; unrequested list projections remain accessible while full PII decryption for those records will fail cleanly.",
                            sum(missing_keys.values()),
                            sorted(missing_keys.keys()),
                        )
            except Exception as audit_err:
                logger.debug("Encryption key audit skipped: %s", audit_err)
        except FieldEncryptionError as enc_err:
            logger.critical("Field encryption configuration error: %s", enc_err)
            if settings.is_production:
                raise RuntimeError(f"Invalid field encryption configuration: {enc_err}") from enc_err

        try:
            from app.db.database import _get_tenant_classes
            from app.db.tenant_enforcement import warm_tenant_enforcement_cache
            _get_tenant_classes()
            warm_count = await asyncio.to_thread(warm_tenant_enforcement_cache)
            logger.info("Tenant class cache pre-warmed: %d classes (%d enforcement targets)", len(_get_tenant_classes()), warm_count)
        except Exception as err:
            logger.error("Failed to pre-warm tenant class cache: %s", str(err))

        # Non-destructive schema drift diagnostic (verifies Alembic head + ORM columns exist)
        try:
            from app.core.readiness import inspect_schema_drift
            drift = await inspect_schema_drift(engine)
            if drift["schema_drift"]:
                logger.critical(
                    "Database schema drift detected on startup: revision_match=%s, missing_tables=%d, missing_columns=%d. Run `alembic upgrade head`.",
                    drift["revision_match"],
                    drift["missing_tables"],
                    drift["missing_columns"],
                )
            else:
                logger.info("Schema readiness check passed (ORM aligned with PostgreSQL and Alembic head).")
        except Exception as schema_err:
            logger.warning("Startup schema check skipped: %s", schema_err)

        try:
            await ensure_superadmin_provisioned()
        except RuntimeError:
            logger.error("Platform owner provisioning requires operator attention.")

        # Seed canonical document categories and templates idempotently
        try:
            from app.services.document_categories import seed_canonical_categories_idempotent
            from app.services.document_templates import seed_canonical_templates_idempotent
            from app.db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                await seed_canonical_categories_idempotent(session)
                await seed_canonical_templates_idempotent(session)
        except Exception as seed_err:
            logger.warning("Document seed notice: %s", str(seed_err))

        # Start document expiry alert background scheduler (guard against duplicate instance)
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from app.services.document_expiry_service import run_document_expiry_scheduler
                existing_sched = getattr(app.state, "expiry_scheduler_task", None)
                if existing_sched is None or existing_sched.done():
                    app.state.expiry_scheduler_task = asyncio.create_task(
                        run_document_expiry_scheduler(),
                        name="document-expiry-scheduler",
                    )
            except Exception as sched_err:
                logger.warning("Expiry scheduler notice: %s", str(sched_err))

        # Validate Celery integration & broker readiness cleanly on startup
        try:
            from app.workers.celery_app import CELERY_AVAILABLE, check_celery_broker_connectivity
            if settings.USE_CELERY:
                if not CELERY_AVAILABLE:
                    msg = "USE_CELERY=true but 'celery' package is not installed in the active Python environment."
                    logger.critical(msg)
                    if settings.is_production:
                        raise RuntimeError(msg)
                else:
                    celery_status = await asyncio.to_thread(check_celery_broker_connectivity, 2.0)
                    if celery_status["broker_reachable"]:
                        logger.info("Celery broker reachable (%s)", celery_status["broker_url"])
                    else:
                        logger.error(
                            "Celery enabled (USE_CELERY=true) but broker unreachable (%s): %s",
                            celery_status["broker_url"],
                            celery_status["error"],
                        )
                        if settings.is_production:
                            raise RuntimeError(
                                f"Celery broker unreachable in production: {celery_status['error']}"
                            )
            else:
                logger.info(
                    "Celery background worker dispatch disabled (USE_CELERY=false, celery_installed=%s); "
                    "using tracked in-process async tasks for local development.",
                    CELERY_AVAILABLE,
                )
        except RuntimeError:
            raise
        except Exception as celery_err:
            logger.warning("Celery startup diagnostic notice: %s", celery_err)

        # Connect to Redis and wrap with instrumentation
        try:
            from app.core.redis_client import redis_client
            await redis_client.connect()
            # Wrap Redis client with instrumentation for dev/staging
            app.state.redis_client = wrap_redis_client(redis_client)
        except Exception as redis_err:
            logger.warning("Redis connection notice: %s", str(redis_err))

        # Start event-loop lag detector
        start_lag_detector()

        # AI Preflight Check (non-blocking, logs actionable guidance)
        try:
            from app.llm.client import get_llm_client
            llm_client = get_llm_client()
            health = await llm_client.check_health()
            base_url = settings.OLLAMA_BASE_URL
            host_only = base_url.replace("http://", "").replace("https://", "").split(":")[0] if base_url else "unknown"
            
            if health.get("healthy"):
                logger.info("AI Preflight: Ollama reachable at %s", base_url)
                installed = health.get("models", [])
                logger.info("AI Preflight: Installed models: %s", installed if installed else "none")
                configured_sql = getattr(settings, "AI_SQL_MODEL", settings.OLLAMA_MODEL)
                configured_answer = getattr(settings, "AI_ANSWER_MODEL", settings.OLLAMA_MODEL)
                logger.info("AI Preflight: Configured models - SQL: %s, Answer: %s", configured_sql, configured_answer)
                
                missing = []
                for model in (configured_sql, configured_answer):
                    if model and model not in installed:
                        # Check base name match
                        model_base = model.split(":")[0]
                        if not any(m.split(":")[0] == model_base for m in installed):
                            missing.append(model)
                
                if missing:
                    logger.warning("AI Preflight: Models missing: %s. Run: ollama pull <model>", missing)
                else:
                    logger.info("AI Preflight: All configured models available")
            else:
                logger.warning(
                    "AI Preflight: Ollama not reachable at %s. "
                    "Local run? set OLLAMA_BASE_URL=http://127.0.0.1:11434 and run `ollama serve`. "
                    "Docker? ensure ollama service is healthy and OLLAMA_BASE_URL=http://ollama:11434",
                    base_url
                )
        except Exception as preflight_err:
            logger.warning("AI Preflight check failed (non-blocking): %s", preflight_err)

        logger.info("Server Running at: http://127.0.0.1:8000")
        if settings.should_enable_docs:
            logger.info(" Swagger API Docs: http://127.0.0.1:8000/docs")
            logger.info(" ReDoc API Docs: http://127.0.0.1:8000/redoc")
        else:
            logger.info(" Public API documentation (/docs, /redoc, /openapi.json) is DISABLED in production.")

        if os.name == "nt" and not settings.is_production and not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                duplicates = await asyncio.to_thread(
                    _find_duplicate_windows_listeners,
                    {os.getpid(), os.getppid()},
                )
                for dup in duplicates:
                    kill_pids = dup["orphan_worker_pids"] or dup["stale_socket_pids"]
                    kill_cmd = " ".join(f"/PID {pid}" for pid in kill_pids)
                    logger.critical(
                        "Duplicate TCP listener on port %d (Windows SO_REUSEADDR conflict): "
                        "stale socket PID(s)=%s, orphan worker PID(s)=%s. "
                        "Incoming API traffic may route to the stale background process instead of this terminal, hiding API logs. "
                        "Terminate stale process(es) with: taskkill /F %s",
                        dup["port"],
                        dup["stale_socket_pids"],
                        dup["orphan_worker_pids"],
                        kill_cmd,
                    )
            except Exception as dup_err:
                logger.debug("Duplicate listener check skipped: %s", dup_err)
    else:
        logger.error("Application started without active database connection. Verify DATABASE_URL in Render environment variables.")
        
    try:
        yield
    except asyncio.CancelledError:
        logger.info("FastAPI lifespan cancelled (normal reload or shutdown signal).")
        raise
    finally:
        logger.info("Initiating graceful application shutdown...")

        # Cancel background document expiry scheduler cleanly
        sched_task = getattr(app.state, "expiry_scheduler_task", None)
        if sched_task is not None:
            if not sched_task.done():
                sched_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sched_task
            app.state.expiry_scheduler_task = None

        # Drain/cancel any in-process fallback payroll background tasks
        try:
            from app.workers.payroll_tasks import shutdown_background_tasks
            await shutdown_background_tasks(timeout=5.0)
        except Exception as bg_err:
            logger.debug("Background task shutdown notice: %s", bg_err)

        # Graceful shutdown of event-loop lag detector
        await stop_lag_detector_async()

        # Graceful shutdown of database pool
        try:
            logger.info("Shutting down database engine connection pool...")
            await engine.dispose()
            logger.info("Database engine shut down cleanly.")
        except Exception as e:
            logger.error("Error shutting down database engine: %s", str(e))

        # Graceful shutdown of Redis connection
        try:
            from app.core.redis_client import redis_client
            await redis_client.disconnect()
        except Exception as e:
            logger.error("Error shutting down Redis connection: %s", str(e))

        # Graceful shutdown of already-initialized HTTP clients
        try:
            from app.llm.providers.registry import get_provider_registry
            registry = get_provider_registry()
            await registry.close_all()
            logger.info("LLM provider registry closed")
        except Exception as e:
            logger.debug("LLM provider cleanup skipped: %s", e)

        try:
            from app.services.stt.providers import _STT_PROVIDERS
            for provider in list(_STT_PROVIDERS.values()):
                if hasattr(provider, "close"):
                    with contextlib.suppress(Exception):
                        await provider.close()
            _STT_PROVIDERS.clear()
        except Exception as e:
            logger.debug("STT provider cleanup skipped: %s", e)

        try:
            from app.services.tts.providers import _TTS_PROVIDERS
            for provider in list(_TTS_PROVIDERS.values()):
                if hasattr(provider, "close"):
                    with contextlib.suppress(Exception):
                        await provider.close()
            _TTS_PROVIDERS.clear()
        except Exception as e:
            logger.debug("TTS provider cleanup skipped: %s", e)


def _find_duplicate_windows_listeners(own_pids: set[int]) -> list[dict[str, object]]:
    """Detect multiple Windows TCP LISTENING sockets sharing our port via SO_REUSEADDR."""
    res = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if res.returncode != 0 or not res.stdout:
        return []

    port_pids: dict[int, set[int]] = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        local_addr = parts[1]
        if ":" not in local_addr:
            continue
        try:
            port = int(local_addr.rsplit(":", 1)[1])
            pid = int(parts[4])
        except ValueError:
            continue
        if pid > 0:
            port_pids.setdefault(port, set()).add(pid)

    duplicates: list[dict[str, object]] = []
    for port, pids in sorted(port_pids.items()):
        if not (pids & own_pids):
            continue
        stale_socket_pids = sorted(pid for pid in pids if pid not in own_pids)
        if not stale_socket_pids:
            continue

        orphan_worker_pids: list[int] = []
        try:
            import psutil

            stale_set = set(stale_socket_pids)
            for proc in psutil.process_iter(["pid", "ppid", "name"]):
                info = proc.info
                proc_pid = info.get("pid")
                if not proc_pid or proc_pid in own_pids:
                    continue
                name = (info.get("name") or "").lower()
                if "python" not in name:
                    continue
                ppid = info.get("ppid")
                if ppid in stale_set:
                    orphan_worker_pids.append(proc_pid)
        except Exception:
            pass

        duplicates.append(
            {
                "port": port,
                "stale_socket_pids": stale_socket_pids,
                "orphan_worker_pids": sorted(set(orphan_worker_pids)),
            }
        )

    return duplicates


def configure_logging() -> None:
    """Configure process logging with line-buffered streams and mandatory PII redaction."""
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if callable(reconfig):
            try:
                reconfig(line_buffering=True)
            except Exception:
                pass

    log_level = getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO)
    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    logging.basicConfig(
        level=log_level,
        format=log_format,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(handler)

    logging.getLogger("app").setLevel(log_level)

    from app.core.structured_logging import PIIRedactionFilter

    # basicConfig is a no-op when an embedding server installed handlers first;
    # attach the filter to every root handler in either case.
    # Leave uvicorn's own handlers untouched because AccessFormatter and
    # ColourizedFormatter (color_message) require record.args to stay intact.
    for handler in root_logger.handlers:
        if not any(isinstance(existing, PIIRedactionFilter) for existing in handler.filters):
            handler.addFilter(PIIRedactionFilter())

    for uv_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uv_logger_name)
        if uv_logger.handlers or uv_logger.propagate:
            if uv_logger.level == logging.NOTSET or uv_logger.level > log_level:
                uv_logger.setLevel(log_level)

    class CancelledErrorFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.msg and "Exception terminating connection" in str(record.msg):
                if record.exc_info:
                    exc_type, exc_val, exc_tb = record.exc_info
                    if exc_type and ("CancelledError" in getattr(exc_type, "__name__", "") or "CancelledError" in str(exc_val)):
                        return False
                if "CancelledError" in record.getMessage():
                    return False
            return True

    db_filter = CancelledErrorFilter()
    for pool_logger_name in ("sqlalchemy.pool.impl.AsyncAdaptedQueuePool", "sqlalchemy.pool"):
        pool_logger = logging.getLogger(pool_logger_name)
        if not any(type(existing).__name__ == "CancelledErrorFilter" for existing in pool_logger.filters):
            pool_logger.addFilter(db_filter)


# Try to use ORJSONResponse for faster JSON serialization
try:
    from fastapi.responses import ORJSONResponse
    DefaultResponse = ORJSONResponse
except ImportError:
    from fastapi.responses import JSONResponse
    DefaultResponse = JSONResponse

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    docs_url = "/docs" if settings.should_enable_docs else None
    redoc_url = "/redoc" if settings.should_enable_docs else None
    openapi_url = "/openapi.json" if settings.should_enable_docs else None

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
        default_response_class=DefaultResponse,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    if not settings.should_enable_docs:
        @app.get("/docs", include_in_schema=False)
        @app.get("/redoc", include_in_schema=False)
        @app.get("/openapi.json", include_in_schema=False)
        @app.get("/api/v1/openapi.json", include_in_schema=False)
        @app.get("/api/v2/openapi.json", include_in_schema=False)
        async def disable_docs_explicitly():
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found"},
                headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
            )

    candidate_origins = list(settings.CORS_ORIGINS) + list(settings.ALLOWED_ORIGINS) + list(settings.BACKEND_CORS_ORIGINS)
    if not settings.is_production:
        candidate_origins.extend(settings.DEV_CORS_ORIGINS)

    # Sanitize: strip whitespace, remove trailing slashes and quotes, ensure no '*' with credentials
    cleaned_origins: list[str] = []
    for origin in candidate_origins:
        if not origin:
            continue
        c = str(origin).strip().strip("'\"").rstrip("/")
        if c and c != "*":
            cleaned_origins.append(c)

    # Deduplicate while preserving exact order
    allowed_origins_list = list(dict.fromkeys(cleaned_origins))

    # Log CORS configuration at startup for production debugging
    logger.info("CORS Configuration: %d origins allowed | environment=%s", len(allowed_origins_list), settings.ENVIRONMENT)
    for origin in allowed_origins_list:
        logger.info("  CORS allowed origin: %s", origin)

    # Session Middleware configuration for secure user sessions via HTTP cookies
    if HAS_SESSION_MIDDLEWARE and SessionMiddleware is not None:
        session_secret = (
            settings.SECRET_KEY.get_secret_value() 
            if hasattr(settings.SECRET_KEY, "get_secret_value") 
            else str(settings.SECRET_KEY)
        )
        # Use __Host- prefix for secure cookies (requires Secure + Path=/ + no Domain)
        # In production, always use secure cookies with SameSite=Strict
        # In development, we still use Secure=True but may need localhost HTTPS (mkcert)
        secure_cookie = settings.ENVIRONMENT.lower() not in {"local", "development", "dev"}
        same_site_policy = "strict" if secure_cookie else "lax"
        cookie_name = "__Host-ofc_session" if secure_cookie else "ofc_session"
        
        app.add_middleware(
            SessionMiddleware,
            secret_key=session_secret,
            session_cookie=cookie_name,
            same_site=same_site_policy,
            https_only=secure_cookie,
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # Match refresh token expiry
        )

    # Performance headers middleware (for dev/staging only) - add early to capture all middleware
    app.add_middleware(PerfHeadersMiddleware)

    # Global rate limiting middleware
    from app.core.rate_limiter import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    # Performance timing middleware
    from app.middleware.timing import TimingMiddleware
    app.add_middleware(TimingMiddleware)

    # GZip compression for responses > 500 bytes, bypassing SSE streams so chunks flush immediately
    class SSEBypassGZipMiddleware:
        """Skip gzip buffering for Server-Sent Events streaming routes."""

        def __init__(self, app: Any, minimum_size: int = 500) -> None:
            self.app = app
            self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

        async def __call__(self, scope, receive, send) -> None:
            if scope.get("type") == "http":
                path = scope.get("path", "")
                accept = ""
                for k, v in scope.get("headers") or ():
                    if k.lower() == b"accept":
                        accept = v.decode("latin-1").lower()
                        break
                if path.endswith("/stream") or "text/event-stream" in accept:
                    await self.app(scope, receive, send)
                    return
            await self.gzip(scope, receive, send)

    app.add_middleware(SSEBypassGZipMiddleware, minimum_size=500)

    # Security Headers Middleware
    from app.middleware.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Tenant Context Middleware - added before RequestID & CORS so RequestID runs early
    from app.middleware.tenant_context import TenantContextMiddleware
    app.add_middleware(TenantContextMiddleware)

    # Request / Correlation ID Middleware (outermost before CORS so error handlers & logs carry request_id)
    from app.middleware.request_id import RequestIDMiddleware
    app.add_middleware(RequestIDMiddleware)

    # CORS Middleware - MUST be added LAST so it executes FIRST (outermost ASGI layer)
    # This guarantees that preflight OPTIONS requests are answered immediately at the network edge
    # with 200 OK / 204 No Content before reaching rate limiters, session managers, or authentication,
    # and ensures all responses (including exception handlers) carry valid CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Authorization", "Content-Type", "Content-Disposition", "X-Request-ID", "X-Correlation-ID", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        max_age=86400,
    )

    install_exception_handlers(app)

    # ── Unified API v1 Router (all endpoints under /api/v1) ───────────────────────
    app.include_router(v1_router)

    # ── Unified API v2 Router (all endpoints under /api/v2) ───────────────────────
    app.include_router(v2_router)

    # ── Standards-based SCIM 2.0 endpoint (not nested under /api/v2) ───────────
    app.include_router(scim_v2_router)

    # ── Public / unprefixed routers ────────────────────────────────────────────
    app.include_router(careers_router, prefix="/api")
    app.include_router(generate_router, prefix="/api")
    app.include_router(intelligence_router, prefix="/api")
    app.include_router(settings_api_router)
    app.include_router(billing_router)
    app.include_router(payments_router)
    app.include_router(onboarding_router)
    app.include_router(hr_admin_onboarding_router)
    app.include_router(core_notifications_router)
    # sidebar_router is already included in v1_router (under /api/v1)
    # Note: v1_router is mounted at /api/v1, so sidebar routes are at /api/v1/sidebar/*
    
    # Authenticated file downloads for private uploads (onboarding, connect)
    app.include_router(file_downloads_router)
    
    # ── HR Interview Dashboard ──────────────────────────────────────────────
    app.include_router(hr_interview_dashboard_router, prefix="/api")

    @app.get("/api/v1/analytics/recruitment", tags=["Recruitment Alternate Routing"])
    @app.get("/analytics/recruitment", tags=["Recruitment Alternate Routing"])
    @app.get("/api/v1/dashboard/recruitment", tags=["Recruitment Alternate Routing"])
    @app.get("/dashboard/recruitment", tags=["Recruitment Alternate Routing"])
    async def get_alternate_recruitment_dashboard(
        claims: dict = Depends(get_current_user_claims),
        db = Depends(get_db_session)
    ):
        from app.services.recruitment_service import RecruitmentService
        from app.repositories.recruitment_repository import RecruitmentRepository
        company_id_raw = claims.get("company_id")
        if not company_id_raw:
            from app.core.exceptions import AppException
            from fastapi import status
            raise AppException(message="Invalid user association.", status_code=status.HTTP_401_UNAUTHORIZED)
        import uuid
        company_id = uuid.UUID(str(company_id_raw))
        repo = RecruitmentRepository(db)
        service = RecruitmentService(session=db, repo=repo, auth_repo=None, employee_repo=None, email_service=None)
        res = await service.get_dashboard_stats(company_id)
        if hasattr(res, "model_dump"):
            res = res.model_dump()
        elif hasattr(res, "dict"):
            res = res.dict()
        return {
            "success": True,
            "message": "Stats retrieved successfully.",
            "data": res,
            "errors": None
        }

    @app.api_route("/health/live", methods=["GET", "HEAD"], tags=["Health Checks"])
    async def liveness():
        return {"status": "alive"}

    @app.api_route("/health", methods=["GET", "HEAD"], tags=["Health Checks"])
    @app.get("/health/ready", tags=["Health Checks"])
    async def health_ready():
        from app.core.readiness import readiness
        result = await readiness(engine)
        return JSONResponse(status_code=200 if result["ready"] else 503, content=result)

    @app.api_route("/", methods=["GET", "HEAD"], status_code=200, tags=["Root"])
    async def root():
        """Root endpoint returning API metadata."""
        data = {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
        }
        if settings.should_enable_docs:
            data["docs_url"] = "/docs"
        return data

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Favicon.ico endpoint to prevent 404 logs."""
        return Response(status_code=204)

    from fastapi.staticfiles import StaticFiles
    import os
    # Security: Mount ONLY non-sensitive public assets. Private uploads (onboarding, connect, face_attendance, qrcodes)
    # MUST be served via authenticated, tenant-scoped download endpoints with path traversal + ownership validation.
    public_subdirs = ["logos", "avatars"]
    for subdir in public_subdirs:
        dir_path = os.path.join(_PROJECT_ROOT, "uploads", subdir)
        try:
            os.makedirs(dir_path, exist_ok=True)
        except PermissionError as err:
            current_uid = os.getuid() if hasattr(os, "getuid") else "N/A"
            logger.warning(
                "Permission notice while ensuring uploads directory '%s' (UID %s): %s",
                dir_path,
                current_uid,
                err,
            )
            if not os.path.isdir(dir_path):
                raise
        app.mount(f"/uploads/{subdir}", StaticFiles(directory=dir_path), name=f"uploads_{subdir}")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    multiprocessing.freeze_support()
    is_dev = not settings.is_production
    host = os.getenv("HOST", "127.0.0.1" if is_dev else "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    if is_dev:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=[os.path.join(_PROJECT_ROOT, "app")],
        )
    else:
        workers = max(1, int(os.getenv("WEB_CONCURRENCY", "4")))
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            workers=workers,
            reload=False,
        )
