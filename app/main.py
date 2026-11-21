"""Main application entrypoint for FastAPI backend."""
# AI Workforce Planning endpoints active

import logging
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
    stop_lag_detector,
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

from app.db.database import engine, get_db_session
from app.middleware.auth import get_current_user_claims
from app.core.config import settings
from app.core.exceptions import install_exception_handlers

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
            from app.db.database import _get_tenant_classes
            _get_tenant_classes()
            logger.info("Tenant class cache pre-warmed: %d classes", len(_get_tenant_classes()))
        except Exception as err:
            logger.error("Failed to pre-warm tenant class cache: %s", str(err))

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

        # Start document expiry alert background scheduler
        try:
            from app.services.document_expiry_service import run_document_expiry_scheduler
            asyncio.create_task(run_document_expiry_scheduler())
        except Exception as sched_err:
            logger.warning("Expiry scheduler notice: %s", str(sched_err))

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
    else:
        logger.error("Application started without active database connection. Verify DATABASE_URL in Render environment variables.")
        
    yield
    
    # Graceful shutdown
    stop_lag_detector()

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


def configure_logging() -> None:
    """Configure process logging with mandatory credential/PII redaction."""
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    from app.core.structured_logging import PIIRedactionFilter

    # basicConfig is a no-op when an embedding server installed handlers first;
    # attach the filter to every root handler in either case.
    for handler in logging.getLogger().handlers:
        if not any(isinstance(existing, PIIRedactionFilter) for existing in handler.filters):
            handler.addFilter(PIIRedactionFilter())

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
    logging.getLogger("sqlalchemy.pool.impl.AsyncAdaptedQueuePool").addFilter(db_filter)
    logging.getLogger("sqlalchemy.pool").addFilter(db_filter)


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

    # GZip compression for responses > 500 bytes (~60-70% size reduction)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Security Headers Middleware
    from app.middleware.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

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
        expose_headers=["Authorization", "Content-Type", "Content-Disposition", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        max_age=86400,
    )

    from app.middleware.tenant_context import TenantContextMiddleware
    app.add_middleware(TenantContextMiddleware)

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
    app.include_router(sidebar_router, prefix="/api")
    app.include_router(sidebar_router)
    
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
    # Security: Mount only specific public subdirectories if needed, NEVER /uploads/documents
    public_subdirs = ["onboarding", "qrcodes", "connect", "face_attendance", "logos", "avatars"]
    for subdir in public_subdirs:
        dir_path = os.path.join("uploads", subdir)
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

    # ---------------------------------------------------------------------------
    # Global Exception Handlers with Explicit CORS Headers
    # ---------------------------------------------------------------------------
    
    def _get_cors_headers(request: Request) -> dict:
        """Generate CORS headers for exception responses."""
        origin = request.headers.get("origin")
        if not origin:
            return {}
        
        cleaned_origin = origin
        is_allowed = origin in allowed_origins_list

        if is_allowed:
            return {
                "Access-Control-Allow-Origin": cleaned_origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Expose-Headers": "Authorization, Content-Type, Content-Disposition, X-Process-Time, X-RateLimit-Limit, X-RateLimit-Remaining",
                "Vary": "Origin",
            }
        return {}

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Global exception handler that logs traceback and returns JSON with CORS headers."""
        import traceback
        logger.error(
            "Unhandled exception on %s %s: %s\n%s",
            request.method,
            request.url.path,
            str(exc),
            traceback.format_exc()
        )
        cors_headers = _get_cors_headers(request)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error.",
                "data": None,
                "errors": [{"field": None, "message": "Internal server error."}],
                "code": "INTERNAL_SERVER_ERROR",
            },
            headers=cors_headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Starlette HTTP exception handler with CORS headers."""
        logger.warning(
            "HTTP exception on %s %s: %d - %s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        cors_headers = _get_cors_headers(request)
        
        message = str(exc.detail) if exc.detail else "Request failed."
        code = None
        if isinstance(exc.detail, dict):
            message = exc.detail.get("message", message)
            code = exc.detail.get("code")
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": message,
                "data": None,
                "errors": [{"field": None, "message": message}],
                "code": code or f"HTTP_{exc.status_code}",
                # Backwards compatibility: Starlette/FastAPI's default
                # HTTPException body is ``{"detail": ...}`` and existing clients
                # read that key directly, so keep it in the envelope.
                "detail": exc.detail if isinstance(exc.detail, dict) else message,
            },
            headers={**cors_headers, **(exc.headers or {})},
        )

    return app


app = create_app()
# Trigger reload
