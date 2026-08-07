"""Background notification tasks."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

try:
    from app.workers.celery_app import celery_app, CELERY_AVAILABLE
    if CELERY_AVAILABLE and celery_app is not None:
        @celery_app.task(name="app.workers.notification_tasks.send_email", max_retries=3)
        def send_email_task(to_email: str, subject: str, html_body: str):
            """Background email send task."""
            import asyncio
            async def _send():
                from app.services.email_service import EmailService
                svc = EmailService()
                await svc.send_email(to_email=to_email, subject=subject, html_body=html_body)
            try:
                asyncio.run(_send())
                logger.info("Email sent to %s | subject: %s", to_email, subject)
                return {"status": "sent", "to": to_email}
            except Exception as exc:
                logger.error("Email task failed: %s", exc)
                raise
except ImportError:
    pass


async def dispatch_send_email(to_email: str, subject: str, html_body: str) -> dict:
    """Dispatch email — Celery or sync."""
    from app.core.config import settings
    if settings.USE_CELERY:
        try:
            from app.workers.notification_tasks import send_email_task
            send_email_task.delay(to_email, subject, html_body)
            return {"status": "queued"}
        except Exception as exc:
            logger.warning("Celery email dispatch failed, sending sync: %s", exc)
    from app.services.email_service import EmailService
    await EmailService().send_email(to_email=to_email, subject=subject, html_body=html_body)
    return {"status": "sent"}
