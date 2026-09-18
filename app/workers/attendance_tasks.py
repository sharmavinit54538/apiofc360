"""Celery task for automated retention and cleanup of Face Attendance photograph files."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)

# Fallback task decorator if Celery is not installed or available
try:
    from app.workers.celery_app import celery_app, CELERY_AVAILABLE
except ImportError:
    celery_app = None
    CELERY_AVAILABLE = False


def _task_decorator(fn):
    if CELERY_AVAILABLE and celery_app:
        return celery_app.task(name=f"app.workers.attendance_tasks.{fn.__name__}", bind=True)(fn)
    return fn


@_task_decorator
def cleanup_old_face_attendance_photos(self=None, retention_days: int | None = None) -> dict:
    """
    Deletes face attendance photographs older than the configured retention window.
    Default retention period is defined by settings.ATTENDANCE_PHOTO_RETENTION_DAYS (default: 90 days).
    """
    days = retention_days or getattr(settings, "ATTENDANCE_PHOTO_RETENTION_DAYS", 90)
    upload_dir = os.path.join(settings.UPLOAD_DIR, "face_attendance")

    if not os.path.isdir(upload_dir):
        logger.info("Face attendance upload directory '%s' does not exist. Skipping cleanup.", upload_dir)
        return {"scanned": 0, "deleted": 0, "freed_bytes": 0, "retention_days": days}

    cutoff_time = time.time() - (days * 86400)
    scanned_count = 0
    deleted_count = 0
    freed_bytes = 0

    logger.info("Starting face attendance photo cleanup: retention=%d days, target_dir=%s", days, upload_dir)

    for entry in os.scandir(upload_dir):
        if not entry.is_file():
            continue

        scanned_count += 1
        try:
            stat = entry.stat()
            if stat.st_mtime < cutoff_time:
                file_size = stat.st_size
                os.remove(entry.path)
                deleted_count += 1
                freed_bytes += file_size
                logger.debug("Deleted expired face attendance photo: %s (%d bytes)", entry.name, file_size)
        except OSError as exc:
            logger.warning("Failed to process/delete expired file %s: %s", entry.path, exc)

    logger.info(
        "Face attendance cleanup completed: scanned=%d, deleted=%d, freed_mb=%.2f",
        scanned_count,
        deleted_count,
        freed_bytes / (1024 * 1024),
    )

    return {
        "scanned": scanned_count,
        "deleted": deleted_count,
        "freed_bytes": freed_bytes,
        "retention_days": days,
    }
