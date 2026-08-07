"""Structured Logging setup.

Configures Python's standard logging module to produce clean JSON formatted logs
with request ID context and timing info in production.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.config import settings


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production monitoring and log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "request_id"):
            log_obj["request_id"] = getattr(record, "request_id")
        if hasattr(record, "user_id"):
            log_obj["user_id"] = getattr(record, "user_id")
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_structured_logging() -> None:
    """Initialize structured logging configuration."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers on re-init
    if root_logger.handlers:
        return

    handler = logging.StreamHandler()
    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        handler.setFormatter(JSONFormatter())
    else:
        fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root_logger.addHandler(handler)
