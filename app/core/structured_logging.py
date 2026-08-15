"""Structured Logging setup.

Configures Python's standard logging module to produce clean JSON formatted logs
with request ID context, timing info, and strict masking of sensitive security credentials
(password hashes, JWTs, bearer tokens, API keys).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.core.config import settings

# Precompiled regex patterns for high performance log sanitization
_BCRYPT_PATTERN = re.compile(r"\$2[abyx]\$[0-9]{2}\$[A-Za-z0-9./]{53}")
_ARGON2_PATTERN = re.compile(r"\$argon2[a-z0-9]+(?:\$[^\s,]+)+")
_PBKDF2_PATTERN = re.compile(r"\$pbkdf2-[a-z0-9-]+\$[^\s,]+")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]*\b")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9\-_.~+/]+=*", re.IGNORECASE)
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    r'''(["']?(?:password|password_hash|new_password|current_password|old_password|'''
    r'''hashed_token|otp_hash|access_token|refresh_token|secret_key|api_key|smtp_password)["']?\s*[:=]\s*["'])([^"'\r\n]+)(["'])''',
    re.IGNORECASE,
)


def mask_sensitive_data(text: str) -> str:
    """Mask raw password hashes, JWTs, Bearer tokens, and sensitive credential fields from string output."""
    if not isinstance(text, str) or not text:
        return text

    # 1. Mask password hashes
    sanitized = _BCRYPT_PATTERN.sub("[MASKED_PASSWORD_HASH]", text)
    sanitized = _ARGON2_PATTERN.sub("[MASKED_PASSWORD_HASH]", sanitized)
    sanitized = _PBKDF2_PATTERN.sub("[MASKED_PASSWORD_HASH]", sanitized)

    # 2. Mask JWT and Bearer tokens
    sanitized = _BEARER_PATTERN.sub("Bearer [MASKED_TOKEN]", sanitized)
    sanitized = _JWT_PATTERN.sub("[MASKED_JWT]", sanitized)

    # 3. Mask sensitive key-value pairs
    sanitized = _SENSITIVE_KEY_VALUE_PATTERN.sub(r"\1[MASKED]\3", sanitized)

    return sanitized


def sanitize_value(val: Any) -> Any:
    """Recursively sanitize strings, dictionaries, and lists."""
    if isinstance(val, str):
        return mask_sensitive_data(val)
    elif isinstance(val, dict):
        return {
            k: ("[MASKED]" if any(s in k.lower() for s in ("password", "token", "secret", "api_key", "otp_hash")) else sanitize_value(v))
            for k, v in val.items()
        }
    elif isinstance(val, (list, tuple, set)):
        return [sanitize_value(item) for item in val]
    return val


class SensitiveDataFilter(logging.Filter):
    """Logging filter that redacts sensitive credentials from log records before dispatch."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_sensitive_data(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_value(record.args)
            elif isinstance(record.args, (tuple, list)):
                record.args = tuple(sanitize_value(a) for a in record.args)
        return True


class JSONFormatter(logging.Formatter):
    """JSON log formatter for production monitoring with automated sensitive data masking."""

    def format(self, record: logging.LogRecord) -> str:
        raw_msg = record.getMessage()
        masked_msg = mask_sensitive_data(raw_msg)

        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": masked_msg,
        }

        if hasattr(record, "request_id"):
            log_obj["request_id"] = getattr(record, "request_id")
        if hasattr(record, "user_id"):
            log_obj["user_id"] = str(getattr(record, "user_id"))
        if record.exc_info:
            raw_exc = self.formatException(record.exc_info)
            log_obj["exception"] = mask_sensitive_data(raw_exc)

        return json.dumps(log_obj)


def setup_structured_logging() -> None:
    """Initialize structured logging configuration with security redaction filters."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers on re-init
    if root_logger.handlers:
        return

    handler = logging.StreamHandler()
    sensitive_filter = SensitiveDataFilter()
    handler.addFilter(sensitive_filter)

    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        handler.setFormatter(JSONFormatter())
    else:
        fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root_logger.addHandler(handler)

