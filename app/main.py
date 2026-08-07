"""Main application entrypoint for FastAPI backend."""
# AI Workforce Planning endpoints active

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse, Response
from starlette.middleware.gzip import GZipMiddleware
try:
    from starlette.middleware.sessions import SessionMiddleware
    HAS_SESSION_MIDDLEWARE = True
except ImportError:
    HAS_SESSION_MIDDLEWARE = False
    SessionMiddleware = None

from sqlalchemy import text

# Routers Import
from app.api.auth import router as auth_router
from app.api.employees import router as employees_router
from app.api.managers import router as managers_router
from app.api.exports import router as exports_router
from app.api.departments import router as departments_router
from app.api.jobs import router as jobs_router
from app.api.assets import router as assets_router
from app.api.timesheets import router as timesheets_router
from app.attendance.routers import router as attendance_router
from app.api.leaves import router as leaves_router
from app.api.careers import router as careers_router
from app.api.applications import router as applications_router
from app.api.interviews import router as interviews_router
from app.api.offers import router as offers_router
from app.api.exits import router as exits_router
from app.api.calendar import router as calendar_router
from app.api.documents import router as documents_router
from app.api.templates import router as templates_router
from app.api.announcements import router as announcements_router
from app.api.news import router as news_router
from app.api.events import router as events_router
from app.api.polls import router as polls_router
from app.api.internal_dashboard import router as internal_dashboard_router
from app.api.ai_copilot import router as ai_copilot_router
from app.api.v1.ai import router as ai_router
from app.api.v1.ai_recruiter import router as ai_recruiter_router
from app.api.v1.ai_attendance import router as ai_attendance_router
from app.api.v1.ai_performance import router as ai_performance_router
from app.api.v1.ai_leave import router as ai_leave_router
from app.api.v1.ai_payroll import router as ai_payroll_router
from app.api.v1.ai_workforce import router as ai_workforce_router, ai_workforce_direct_router
from app.api.v1.employee_health import router as employee_health_router
from app.api.v1.policy_ai import router as policy_ai_router
from app.api.v1.meeting_ai import router as meeting_ai_router
from app.api.v1.compliance_monitor import router as compliance_monitor_router
from app.api.v1.chat_assistant import router as chat_assistant_router
from app.api.v1.analytics_center import router as analytics_center_router
from app.api.v1.ai_brain import router as ai_brain_router
from app.api.ai_insights import router as ai_insights_router, ai_analytics_router, analytics_alias_router
from app.api.settings import router as settings_api_router
from app.api.sidebar import router as sidebar_router
from app.api.cto.dashboard import router as cto_dashboard_router
from app.api.onboarding import router as onboarding_router
from app.api.employee_onboarding_api import router as employee_onboarding_api_router
from app.api.employee_onboarding_admin_api import router as employee_onboarding_admin_api_router
from app.api.hr_admin_onboarding import router as hr_admin_onboarding_router
from app.api.hierarchy import router as hierarchy_router
from app.api.talent_pool import router as talent_pool_router
from app.api.requisitions import router as requisitions_router
from app.api.vendors import router as vendors_router
from app.api.crm import router as crm_router
from app.api.referrals import router as referrals_router
from app.api.automation import router as automation_router
from app.api.scorecards import router as scorecards_router
from app.api.recruitment_analytics import router as recruitment_analytics_router
from app.api.recruitment import router as recruitment_router
from app.api.ats import router as ats_router
from app.api.v2.document_intelligence import router as doc_intel_router
from app.api.v2.employee_support import router as emp_support_router
from app.api.v2.interview_bot import router as interview_bot_router
from app.api.v2.hr_analytics_api import router as hr_analytics_router
from app.api.v2.hr_workflow_api import router as hr_workflow_router
from app.api.v2.payroll_api import router as payroll_router
from app.api.v2.tax_api import router as tax_router
from app.api.v2.performance_api import router as performance_router
from app.api.v2.policy_api import router as policy_router
from app.api.v2.wellness_api import router as wellness_router
from app.api.v2.travel_api import router as travel_router
from app.api.v2.reports_api import router as reports_router
from app.api.v2.productivity_api import router as productivity_router
from app.api.v2.goal_generator_api import router as goals_router
from app.api.v2.compensation_api import router as compensation_router
from app.api.v2.behavioural_api import router as behavioural_router
from app.api.v2.email_generator_api import router as email_router
from app.api.v2.emotion_chatbot_api import router as emotions_router
from app.api.v2.org_intelligence_apis import org_map_router, skill_gap_router, shift_router, digital_twin_router
from app.api.v2.employee_intelligence_apis import voice_router, mood_router, career_router, learning_router
from app.api.v2.enterprise_intelligence_apis import workforce_router, talent_router, meetings_router, compliance_router, risk_router, copilot_router
from app.api.global_notifications import router as global_notifications_router
from app.api.generate_api import router as generate_router

from app.db.database import engine, get_db_session
from app.middleware.auth import get_current_user_claims
from app.core.config import settings
from app.core.exceptions import install_exception_handlers

logger = logging.getLogger("app.main")


async def auto_screen_unscreened_leads():
    import asyncio
    import os
    import logging
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.db.database import AsyncSessionLocal
    from app.models.recruitment import Application, Candidate
    from app.models.ai_recruitment import CandidateMatchScore
    from app.services.recruitment_service import RecruitmentService
    from app.repositories.recruitment_repository import RecruitmentRepository

    logger = logging.getLogger("app.main")
    logger.info("Auto-screening: checking for unscreened candidate leads...")
    
    # Give the app 2 seconds to finish starting up
    await asyncio.sleep(2)
    
    async with AsyncSessionLocal() as session:
        try:
            # Query all applications with jobs and candidates eager loaded
            stmt = select(Application).options(
                selectinload(Application.job),
                selectinload(Application.candidate)
            )
            apps_res = await session.execute(stmt)
            apps = apps_res.scalars().all()
            
            # Query candidate IDs that already have a match score
            score_res = await session.execute(select(CandidateMatchScore.candidate_id))
            scored_candidate_ids = set(score_res.scalars().all())
            
            unscreened_apps = [a for a in apps if a.candidate_id not in scored_candidate_ids]
            logger.info("Auto-screening: found %s unscreened applications", len(unscreened_apps))
            
            for app in unscreened_apps:
                candidate = app.candidate
                if not candidate and app.email:
                    # Look up candidate by email
                    cand_res = await session.execute(
                        select(Candidate).where(Candidate.email == app.email.lower().strip())
                    )
                    candidate = cand_res.scalar_one_or_none()
                    if not candidate:
                        # Auto-create Candidate
                        names = (app.first_name + " " + app.last_name).split(" ")
                        first_name = names[0]
                        last_name = " ".join(names[1:]) if len(names) > 1 else "Candidate"
                        candidate = Candidate(
                            first_name=first_name,
                            last_name=last_name,
                            email=app.email.lower().strip(),
                            phone=app.phone or "0000000000",
                            location=f"{app.city or ''}, {app.state or ''}, {app.country or ''}".strip(", "),
                            years_experience=app.experience_years or 0.0,
                            current_company=app.current_company or "",
                            current_role=app.current_designation or "",
                            expected_salary=app.expected_ctc or 0.0,
                            source="Imported Lead",
                            is_talent_pool=False,
                        )
                        session.add(candidate)
                        await session.commit()
                        await session.refresh(candidate)
                    
                    app.candidate_id = candidate.id
                    await session.commit()
                
                if not candidate:
                    continue
                
                # Fetch resume file if candidate has one
                resume_path = candidate.resume_path
                resume_name = candidate.resume_name or "resume.pdf"
                file_size = 0
                if resume_path and os.path.exists(resume_path):
                    file_size = os.path.getsize(resume_path)
                else:
                    resume_path = None
                
                # Initialize Service and trigger task
                repo = RecruitmentRepository(session)
                service = RecruitmentService(
                    session=session,
                    repo=repo,
                    auth_repo=None,
                    employee_repo=None,
                    email_service=None
                )
                
                logger.info("Auto-screening candidate application %s (email: %s) without resume", app.id, candidate.email)
                await service.screen_candidate_resume_task(
                    application_id=app.id,
                    candidate_id=candidate.id,
                    job_id=app.job_id,
                    resume_path=resume_path or "",
                    resume_name=resume_name,
                    file_size=file_size
                )
                
        except Exception as e:
            logger.exception("Auto-screening: background check failed: %s", str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler to check database connectivity on startup."""
    logger.info("Initializing database connectivity check on startup...")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connectivity check: SUCCESSFUL.")
        
        # Ensure all tables exist
        from app.db.base import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully.")
        
        # Trigger background auto screening check for unscreened leads
        import asyncio
        asyncio.create_task(auto_screen_unscreened_leads())
        
        # Pre-warm tenant class cache
        from app.db.database import _get_tenant_classes
        _get_tenant_classes()
        logger.info("Tenant class cache pre-warmed: %d classes", len(_get_tenant_classes()))
        
    except Exception as e:
        logger.warning("Database connectivity or startup initialization warning: %s", str(e))
    yield


def configure_logging() -> None:
    """Configure process logging."""
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

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


from fastapi.responses import JSONResponse
DefaultResponse = JSONResponse

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
        default_response_class=DefaultResponse,
    )

    # Hardcoded ports so browser doesn't throw Network Error for localhost:8080
    allowed_origins_list = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ]
    
    # Agar .env me kuch origins hain toh unhe bhi merge kar lete hain
    if settings.ALLOWED_ORIGINS:
        allowed_origins_list.extend(settings.ALLOWED_ORIGINS)
    if settings.BACKEND_CORS_ORIGINS:
        allowed_origins_list.extend(settings.BACKEND_CORS_ORIGINS)

    @app.middleware("http")
    async def custom_cors_middleware(request, call_next):
        origin = request.headers.get("origin")
        if request.method == "OPTIONS":
            response = Response(status_code=204)
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
            else:
                response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Max-Age"] = "86400"
            return response

        try:
            response = await call_next(request)
        except Exception as exc:
            response = JSONResponse(
                status_code=500,
                content={"success": False, "message": str(exc), "data": None, "errors": None}
            )

        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        else:
            response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    # GZip compression for responses > 500 bytes (~60-70% size reduction)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Performance timing middleware
    from app.middleware.timing import TimingMiddleware
    app.add_middleware(TimingMiddleware)

    # Session Middleware configuration for secure user sessions via HTTP cookies
    if HAS_SESSION_MIDDLEWARE and SessionMiddleware is not None:
        session_secret = (
            settings.SECRET_KEY.get_secret_value() 
            if hasattr(settings.SECRET_KEY, "get_secret_value") 
            else str(settings.SECRET_KEY)
        )
        app.add_middleware(
            SessionMiddleware,
            secret_key=session_secret,
            session_cookie="ofc_session",
            same_site="lax",
            https_only=not settings.DEBUG,  # False for development/localhost, True for production
        )

    install_exception_handlers(app)
    app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
    app.include_router(employees_router, prefix=settings.API_V1_PREFIX)
    app.include_router(managers_router, prefix=settings.API_V1_PREFIX)
    app.include_router(departments_router, prefix=settings.API_V1_PREFIX)
    app.include_router(announcements_router, prefix=settings.API_V1_PREFIX)
    app.include_router(announcements_router, prefix="/api/v1/company")
    app.include_router(jobs_router, prefix=settings.API_V1_PREFIX)
    app.include_router(jobs_router, prefix="/api/v1/recruitment")
    app.include_router(assets_router, prefix=settings.API_V1_PREFIX)
    app.include_router(applications_router, prefix=settings.API_V1_PREFIX)
    app.include_router(applications_router, prefix="/api")
    app.include_router(interviews_router, prefix=settings.API_V1_PREFIX)
    app.include_router(interviews_router, prefix="/api/v1/recruitment")
    app.include_router(offers_router, prefix=settings.API_V1_PREFIX)
    app.include_router(offers_router, prefix="/api/v1/recruitment")
    app.include_router(exits_router, prefix=settings.API_V1_PREFIX)
    app.include_router(calendar_router, prefix=settings.API_V1_PREFIX)
    app.include_router(documents_router, prefix=settings.API_V1_PREFIX)
    app.include_router(timesheets_router, prefix=settings.API_V1_PREFIX)
    app.include_router(attendance_router, prefix=settings.API_V1_PREFIX)
    app.include_router(leaves_router, prefix=settings.API_V1_PREFIX)
    app.include_router(templates_router, prefix=settings.API_V1_PREFIX)
    app.include_router(news_router, prefix=settings.API_V1_PREFIX)
    app.include_router(events_router, prefix=settings.API_V1_PREFIX)
    app.include_router(polls_router, prefix=settings.API_V1_PREFIX)
    app.include_router(internal_dashboard_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_copilot_router, prefix=settings.API_V1_PREFIX)
    app.include_router(chat_assistant_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_recruiter_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_attendance_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_performance_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_leave_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_payroll_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_workforce_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_workforce_direct_router, prefix=settings.API_V1_PREFIX)
    app.include_router(employee_health_router, prefix=settings.API_V1_PREFIX)
    app.include_router(policy_ai_router, prefix=settings.API_V1_PREFIX)
    app.include_router(meeting_ai_router, prefix=settings.API_V1_PREFIX)
    app.include_router(compliance_monitor_router, prefix=settings.API_V1_PREFIX)
    app.include_router(analytics_center_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_brain_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_insights_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ai_analytics_router, prefix=settings.API_V1_PREFIX)
    app.include_router(analytics_alias_router, prefix=settings.API_V1_PREFIX)
    app.include_router(settings_api_router, prefix=settings.API_V1_PREFIX)
    app.include_router(settings_api_router, prefix="/api")
    app.include_router(settings_api_router)
    app.include_router(sidebar_router, prefix=settings.API_V1_PREFIX)
    app.include_router(cto_dashboard_router, prefix=settings.API_V1_PREFIX)
    app.include_router(cto_dashboard_router, prefix="/api")
    app.include_router(onboarding_router, prefix=settings.API_V1_PREFIX)
    app.include_router(employee_onboarding_api_router, prefix=settings.API_V1_PREFIX)
    app.include_router(employee_onboarding_admin_api_router, prefix=settings.API_V1_PREFIX)
    app.include_router(hr_admin_onboarding_router, prefix=settings.API_V1_PREFIX)
    app.include_router(hierarchy_router, prefix=settings.API_V1_PREFIX)
    app.include_router(exports_router, prefix=settings.API_V1_PREFIX)
    app.include_router(talent_pool_router, prefix=settings.API_V1_PREFIX)
    app.include_router(requisitions_router, prefix=settings.API_V1_PREFIX)
    app.include_router(vendors_router, prefix=settings.API_V1_PREFIX)
    app.include_router(crm_router, prefix=settings.API_V1_PREFIX)
    app.include_router(referrals_router, prefix=settings.API_V1_PREFIX)
    app.include_router(automation_router, prefix=settings.API_V1_PREFIX)
    app.include_router(scorecards_router, prefix=settings.API_V1_PREFIX)
    app.include_router(recruitment_analytics_router, prefix=settings.API_V1_PREFIX)
    app.include_router(recruitment_router, prefix=settings.API_V1_PREFIX)
    app.include_router(recruitment_router, prefix="/api")
    app.include_router(ats_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ats_router, prefix="/api")
    app.include_router(careers_router, prefix="/api")
    app.include_router(doc_intel_router, prefix="/api/v2")
    app.include_router(emp_support_router, prefix="/api/v2")
    app.include_router(interview_bot_router, prefix="/api/v2")
    app.include_router(hr_analytics_router, prefix="/api/v2")
    app.include_router(hr_analytics_router, prefix=settings.API_V1_PREFIX)
    app.include_router(hr_workflow_router, prefix="/api/v2")
    app.include_router(payroll_router, prefix="/api/v2")
    app.include_router(payroll_router, prefix=settings.API_V1_PREFIX)
    app.include_router(payroll_router, prefix="/api")
    app.include_router(tax_router, prefix=settings.API_V1_PREFIX)
    app.include_router(tax_router, prefix="/api/v2")
    app.include_router(tax_router, prefix="/api")
    app.include_router(performance_router, prefix="/api/v2")
    app.include_router(performance_router, prefix="/api/v1/api/v2")
    app.include_router(policy_router, prefix="/api/v2")
    app.include_router(wellness_router, prefix="/api/v2")
    app.include_router(travel_router, prefix="/api/v2")
    app.include_router(reports_router, prefix="/api/v2")
    app.include_router(reports_router, prefix=settings.API_V1_PREFIX)
    app.include_router(reports_router, prefix="/api")
    app.include_router(reports_router)
    app.include_router(productivity_router, prefix="/api/v2")
    app.include_router(goals_router, prefix="/api/v2")
    app.include_router(compensation_router, prefix="/api/v2")
    app.include_router(behavioural_router, prefix="/api/v2")
    app.include_router(email_router, prefix="/api/v2")
    app.include_router(emotions_router, prefix="/api/v2")
    app.include_router(org_map_router, prefix="/api/v2")
    app.include_router(skill_gap_router, prefix="/api/v2")
    app.include_router(shift_router, prefix="/api/v2")
    app.include_router(digital_twin_router, prefix="/api/v2")
    app.include_router(voice_router, prefix="/api/v2")
    app.include_router(mood_router, prefix="/api/v2")
    app.include_router(career_router, prefix="/api/v2")
    app.include_router(learning_router, prefix="/api/v2")
    app.include_router(workforce_router, prefix="/api/v2")
    app.include_router(talent_router, prefix="/api/v2")
    app.include_router(meetings_router, prefix="/api/v2")
    app.include_router(compliance_router, prefix="/api/v2")
    app.include_router(risk_router, prefix="/api/v2")
    app.include_router(copilot_router, prefix="/api/v2")
    app.include_router(global_notifications_router, prefix=settings.API_V1_PREFIX)
    app.include_router(generate_router, prefix="/api")
    app.include_router(generate_router)

    app.include_router(jobs_router)  # Unprefixed fallback
    app.include_router(recruitment_analytics_router)  # Unprefixed fallback

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

    @app.api_route("/health", methods=["GET", "HEAD"], status_code=200, tags=["Health"])
    async def health_check():
        """Fast health check endpoint to verify backend and database status."""
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {
                "status": "healthy",
                "database": "connected",
            }
        except Exception as e:
            logger.error("Health check failed: DB is unreachable. Error: %s", e)
            import json
            return Response(
                content=json.dumps({
                    "status": "unhealthy",
                    "database": "disconnected",
                    "error": str(e)
                }),
                status_code=503,
                media_type="application/json"
            )

    @app.get("/health", tags=["Health Checks"])
    async def health():
        """Liveness probe endpoint."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    @app.get("/health/ready", tags=["Health Checks"])
    async def health_ready():
        """Readiness probe checking DB and LLM connectivity."""
        db_healthy = False
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_healthy = True
        except Exception:
            pass

        from app.llm.client import get_llm_client
        llm_health = await get_llm_client().check_health()

        ready = db_healthy and llm_health.get("healthy", False)
        status_code = 200 if ready else 503

        return JSONResponse(
            status_code=status_code,
            content={
                "ready": ready,
                "database": "connected" if db_healthy else "disconnected",
                "llm": llm_health,
            }
        )

    @app.api_route("/", methods=["GET", "HEAD"], status_code=200, tags=["Root"])
    async def root():
        """Root endpoint returning API metadata."""
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
            "docs_url": "/docs"
        }

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Favicon.ico endpoint to prevent 404 logs."""
        return Response(status_code=204)

    from fastapi.staticfiles import StaticFiles
    import os
    os.makedirs("uploads", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

    return app


app = create_app()
# Trigger reload