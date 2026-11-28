"""Celery application configuration for OFC360 background processing."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings

logger = logging.getLogger(__name__)


def redact_broker_url(url: str | None) -> str:
    """Return broker/backend URL with embedded password masked for safe logging."""
    if not url:
        return "<unconfigured>"
    try:
        parts = urlsplit(str(url))
        if parts.password is None:
            return str(url)
        user_part = f"{parts.username}:***@" if parts.username else ":***@".lstrip(":")
        if parts.username:
            auth = f"{parts.username}:***@"
        else:
            auth = ":***@"
        host_port = f"{parts.hostname or ''}{f':{parts.port}' if parts.port else ''}"
        return urlunsplit((parts.scheme, f"{auth}{host_port}", parts.path, parts.query, parts.fragment))
    except Exception:
        return "<redacted-url>"


try:
    from celery import Celery

    celery_app = Celery(
        "ofc360",
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
        task_track_started=True,
        worker_send_task_events=True,
        result_expires=86400,          # Results expire after 24 hours
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=5,
        broker_transport_options={
            "visibility_timeout": 3600,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
        result_backend_transport_options={
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
        task_routes={
            "app.workers.resume_tasks.*": {"queue": "resume_parsing"},
            "app.workers.notification_tasks.*": {"queue": "notifications"},
        },
        task_default_queue="default",
        beat_schedule={
            "execute-durable-automation": {
                "task": "app.workers.automation_tasks.drain",
                "schedule": 15.0,
            },
            "recover-abandoned-payroll-claims": {
                "task": "app.workers.payroll_tasks.recover_abandoned_payroll_runs_task",
                "schedule": 60.0,
            },
        },
    )

    CELERY_AVAILABLE = True
    if settings.USE_CELERY:
        logger.info(
            "Celery enabled and configured (broker=%s, backend=%s)",
            redact_broker_url(settings.CELERY_BROKER_URL),
            redact_broker_url(settings.CELERY_RESULT_BACKEND),
        )
        if os.name == "nt":
            logger.info(
                "Windows Celery notice: prefork pool is unsupported on native Windows; "
                "run local Celery workers with '--pool=solo' or inside WSL2/Docker Linux containers for production."
            )
    else:
        logger.debug(
            "Celery package installed (USE_CELERY=false — using tracked in-process asyncio fallback in local dev)"
        )

except ImportError:
    logger.warning(
        "celery package is not installed — Celery background task execution disabled (install celery[redis] or set USE_CELERY=false for in-process fallback)"
    )
    celery_app = None  # type: ignore[assignment]
    CELERY_AVAILABLE = False


def check_celery_broker_connectivity(timeout_seconds: float = 2.0) -> dict[str, Any]:
    """Validate Celery availability and broker reachability without exposing credentials."""
    status_info: dict[str, Any] = {
        "celery_installed": CELERY_AVAILABLE,
        "enabled": bool(settings.USE_CELERY),
        "broker_url": redact_broker_url(settings.CELERY_BROKER_URL),
        "result_backend": redact_broker_url(settings.CELERY_RESULT_BACKEND),
        "broker_reachable": False,
        "error": None,
    }
    if not CELERY_AVAILABLE or celery_app is None:
        status_info["error"] = "celery package is not installed"
        return status_info

    try:
        with celery_app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=1, interval_start=0, timeout=timeout_seconds)
        status_info["broker_reachable"] = True
    except Exception as exc:
        status_info["error"] = f"{type(exc).__name__}: {exc}"
    return status_info
