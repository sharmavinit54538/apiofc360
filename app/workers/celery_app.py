"""Celery application configuration for Aurix-AI background processing."""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from celery import Celery

    celery_app = Celery(
        "aurix_ai",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.workers.resume_tasks",
            "app.workers.screening_tasks",
            "app.workers.automation_tasks",
            "app.workers.notification_tasks",
            "app.workers.payroll_tasks",
        ],
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
        task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
        worker_prefetch_multiplier=1,  # Fairness for long tasks
        task_acks_late=True,           # Re-queue on worker crash
        task_reject_on_worker_lost=True,
        result_expires=86400,          # Results expire after 24 hours
        task_routes={
            "app.workers.resume_tasks.*": {"queue": "resume_parsing"},
            "app.workers.notification_tasks.*": {"queue": "notifications"},
        },
        task_default_queue="default",
        beat_schedule={
            "execute-durable-automation": {
                "task": "app.workers.automation_tasks.drain", "schedule": 15.0,
            },
            "recover-abandoned-payroll-claims": {
                "task": "app.workers.payroll_tasks.recover_abandoned_payroll_runs_task",
                "schedule": 60.0,
            },
        },
    )

    CELERY_AVAILABLE = True
    logger.info("Celery configured")

except ImportError:
    logger.warning("celery not installed — background task processing disabled")
    celery_app = None  # type: ignore[assignment]
    CELERY_AVAILABLE = False
