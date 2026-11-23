"""Reliable Celery screening jobs; explicit company scope at every entry point."""
import asyncio
import uuid
from app.workers.celery_app import celery_app
from app.db.base import tenant_id_ctx


if celery_app is not None:
    @celery_app.task(name="app.workers.screening_tasks.screen_application", autoretry_for=(Exception,),
                     retry_backoff=True, max_retries=3, acks_late=True)
    def screen_application_task(application_id, company_id):
        from app.services.recruitment_screening import screen_application
        token = tenant_id_ctx.set(None)
        try:
            return asyncio.run(screen_application(uuid.UUID(application_id), uuid.UUID(company_id)))
        finally:
            tenant_id_ctx.reset(token)
