"""Background notification tasks."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from app.workers.celery_app import celery_app, CELERY_AVAILABLE
    if CELERY_AVAILABLE and celery_app is not None:
        @celery_app.task(
            bind=True,
            name="app.workers.notification_tasks.send_email",
            max_retries=3,
            default_retry_delay=30,
            acks_late=True,
        )
        def send_email_task(self, to_email: str, subject: str, html_body: str):
            """Background email send task."""
            import asyncio

            async def _send():
                from app.services.email_service import send_email
                await send_email(to_email=to_email, subject=subject, html_content=html_body)

            try:
                asyncio.run(_send())
                logger.info("Background email sent | subject=%r", subject)
                return {"status": "sent"}
            except Exception as exc:
                logger.error("Email task failed | subject=%r | error=%s", subject, exc)
                raise self.retry(exc=exc, countdown=min(120, 2 ** self.request.retries * 10))
except ImportError:
    pass


async def dispatch_send_email(to_email: str, subject: str, html_body: str) -> dict:
    """Dispatch email — Celery when enabled or in-process async fallback."""
    from app.core.config import settings
    if settings.USE_CELERY:
        try:
            from app.workers.notification_tasks import send_email_task
            send_email_task.delay(to_email, subject, html_body)
            return {"status": "queued"}
        except Exception as exc:
            if settings.is_production:
                logger.error("Celery email dispatch failed in production: %s", exc)
                raise RuntimeError(f"Failed to enqueue email task: {exc}") from exc
            logger.warning("Celery email dispatch failed in dev, sending directly: %s", exc)
    from app.services.email_service import send_email
    await send_email(to_email=to_email, subject=subject, html_content=html_body)
    return {"status": "sent"}
