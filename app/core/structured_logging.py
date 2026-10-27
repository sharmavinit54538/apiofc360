"""Structured logging with credential and PII redaction.

Every handler installed by :func:`setup_structured_logging` receives a filter
that sanitizes message templates, positional/dictionary arguments and common
``extra=`` fields.  The formatter performs a second pass as defence in depth.
No plaintext government identifier or bank account number should be logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import settings


# Precompiled regex patterns for high performance log sanitization.
_BCRYPT_PATTERN = re.compile(r"\$2[abyx]\$[0-9]{2}\$[A-Za-z0-9./]{53}")
_ARGON2_PATTERN = re.compile(r"\$argon2[a-z0-9]+(?:\$[^\s,]+)+")
_PBKDF2_PATTERN = re.compile(r"\$pbkdf2-[a-z0-9-]+\$[^\s,]+")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.[A-Za-z0-9-_.+/=]*\b")
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9\-_.~+/]+=*", re.IGNORECASE)

_CREDENTIAL_KEYS = (
    "password",
    "password_hash",
    "new_password",
    "current_password",
    "old_password",
    "hashed_token",
    "otp_hash",
    "access_token",
    "refresh_token",
    "secret_key",
    "api_key",
    "smtp_password",
)
PII_LOG_KEYS = frozenset(
    {
        "aadhaar",
        "aadhaar_number",
        "aadhaarnumber",
        "pan",
        "pan_number",
        "pannumber",
        "account_number",
        "accountnumber",
        "bank_account_number",
        "bankaccountnumber",
        "uan",
        "uan_number",
        "uannumber",
        "passport",
        "passport_number",
        "passportnumber",
        "voter_id",
        "voterid",
        "ifsc",
        "ifsc_code",
        "ifscode",
        "bank_ifsc",
        "driving_license",
        "driving_license_number",
        "drivinglicense",
        "drivinglicensenumber",
        "nominee_aadhaar",
        "nominee_aadhaar_number",
        "aadhaar_no",
        "pan_no",
        "passport_no",
        "voter_id_number",
    }
)
_ALL_SENSITIVE_KEYS = _CREDENTIAL_KEYS + tuple(sorted(PII_LOG_KEYS))
_KEY_ALTERNATION = "|".join(re.escape(key) for key in _ALL_SENSITIVE_KEYS)

# Handles Python dictionaries and log templates: key=value / 'key': 'value'.
_SENSITIVE_KEY_VALUE_PATTERN = re.compile(
    rf'''(["']?(?:{_KEY_ALTERNATION})["']?\s*[:=]\s*["'])(?!%|\[MASKED)([^"'\r\n]+)(["'])''',
    re.IGNORECASE,
)
# Handles unquoted JSON-like numeric/null values and key=value logs.
_SENSITIVE_UNQUOTED_KEY_VALUE_PATTERN = re.compile(
    rf'''(["']?(?:{_KEY_ALTERNATION})["']?\s*[:=]\s*)(?!%|\[MASKED)([^,"'\s}}\]]+)''',
    re.IGNORECASE,
)

# Free-form values are also redacted when a developer accidentally logs a raw
# value without its field name.  The conservative numeric rule includes bank
# accounts, Aadhaar and UAN; over-redaction is preferable to a PII disclosure.
_PAN_VALUE_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
_FORMATTED_LONG_ID_PATTERN = re.compile(r"(?<![\d-])(?:\d[ -]?){8,17}\d(?![\d-])")
_LONG_NUMERIC_ID_PATTERN = re.compile(r"(?<![\d-])\d{9,18}(?![\d-])")
_PASSPORT_VALUE_PATTERN = re.compile(r"\b[A-Z][0-9]{7}\b", re.IGNORECASE)
_VOTER_VALUE_PATTERN = re.compile(r"\b[A-Z]{3}[0-9]{7}\b", re.IGNORECASE)

PII_MASK = "[MASKED_PII]"


def mask_sensitive_data(text: str) -> str:
    """Mask credentials, tokens and raw PII in arbitrary string output."""

    if not isinstance(text, str) or not text:
        return text

    sanitized = _BCRYPT_PATTERN.sub("[MASKED_PASSWORD_HASH]", text)
    sanitized = _ARGON2_PATTERN.sub("[MASKED_PASSWORD_HASH]", sanitized)
    sanitized = _PBKDF2_PATTERN.sub("[MASKED_PASSWORD_HASH]", sanitized)
    sanitized = _BEARER_PATTERN.sub("Bearer [MASKED_TOKEN]", sanitized)
    sanitized = _JWT_PATTERN.sub("[MASKED_JWT]", sanitized)

    # Key-based redaction happens before free-form expressions so placeholders
    # are not partially matched by a second expression.
    sanitized = _SENSITIVE_KEY_VALUE_PATTERN.sub(r"\1[MASKED]\3", sanitized)
    sanitized = _SENSITIVE_UNQUOTED_KEY_VALUE_PATTERN.sub(r"\1[MASKED]", sanitized)
    sanitized = _PAN_VALUE_PATTERN.sub(PII_MASK, sanitized)
    sanitized = _FORMATTED_LONG_ID_PATTERN.sub(PII_MASK, sanitized)
    sanitized = _PASSPORT_VALUE_PATTERN.sub(PII_MASK, sanitized)
    sanitized = _VOTER_VALUE_PATTERN.sub(PII_MASK, sanitized)
    sanitized = _LONG_NUMERIC_ID_PATTERN.sub(PII_MASK, sanitized)
    return sanitized


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized in PII_LOG_KEYS:
        return True
    return any(
        part in normalized
        for part in ("password", "token", "secret", "api_key", "otp_hash")
    )


def _mask_for_key(key: Any) -> str:
    normalized = str(key).strip().lower().replace("-", "_")
    return PII_MASK if normalized in PII_LOG_KEYS else "[MASKED]"


def sanitize_value(val: Any) -> Any:
    """Recursively sanitize strings, dictionaries, lists and exception args."""

    if isinstance(val, str):
        return mask_sensitive_data(val)
    if isinstance(val, dict):
        return {
            key: (_mask_for_key(key) if _is_sensitive_key(key) else sanitize_value(value))
            for key, value in val.items()
        }
    if isinstance(val, (list, tuple, set)):
        return [sanitize_value(item) for item in val]
    return val


class PIIRedactionFilter(logging.Filter):
    """Redact sensitive keys and identifier-shaped values from log records."""

    _RESERVED_RECORD_KEYS = frozenset(
        {
            "args",
            "msg",
            "exc_info",
            "exc_text",
            "stack_info",
            "thread",
            "threadName",
            "process",
            "processName",
        }
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_value(record.args)
            elif isinstance(record.args, (tuple, list)):
                record.args = tuple(sanitize_value(arg) for arg in record.args)

        # Render printf-style arguments before applying key-based expressions.
        # Otherwise a template such as ``pan_number=%s`` could have its ``%s``
        # replaced while the argument remains, causing a logging formatting
        # error. Rendering first also redacts short identifiers by their key.
        if record.args or not isinstance(record.msg, str):
            try:
                record.msg = mask_sensitive_data(record.getMessage())
                record.args = ()
            except (TypeError, ValueError):
                # Preserve logging's normal error handling for malformed
                # templates while still sanitizing the original message.
                if isinstance(record.msg, str):
                    record.msg = mask_sensitive_data(record.msg)
                elif isinstance(record.msg, (dict, list, tuple, set)):
                    record.msg = sanitize_value(record.msg)
        else:
            record.msg = mask_sensitive_data(record.msg)

        # ``logger.info(..., extra={"pan_number": ...})`` bypasses msg args.
        # Scrub those attributes as well, including nested context dictionaries.
        for key, value in list(record.__dict__.items()):
            if key in self._RESERVED_RECORD_KEYS:
                continue
            if _is_sensitive_key(key):
                setattr(record, key, _mask_for_key(key))
            elif isinstance(value, (dict, list, tuple, set)):
                setattr(record, key, sanitize_value(value))

        if record.exc_text:
            record.exc_text = mask_sensitive_data(record.exc_text)
        return True


class SensitiveDataFilter(PIIRedactionFilter):
    """Backward-compatible name for the combined credential/PII filter."""


class JSONFormatter(logging.Formatter):
    """JSON log formatter with automated sensitive-data masking."""

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
    """Initialize structured logging with credential and PII redaction."""

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers on re-init, but never leave pre-existing
    # embedding-server handlers without the mandatory PII filter.
    if root_logger.handlers:
        for existing_handler in root_logger.handlers:
            if not any(isinstance(item, PIIRedactionFilter) for item in existing_handler.filters):
                existing_handler.addFilter(PIIRedactionFilter())
        return

    handler = logging.StreamHandler()
    handler.addFilter(SensitiveDataFilter())

    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        handler.setFormatter(JSONFormatter())
    else:
        fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        handler.setFormatter(logging.Formatter(fmt))

    root_logger.addHandler(handler)


__all__ = [
    "JSONFormatter",
    "PII_LOG_KEYS",
    "PII_MASK",
    "PIIRedactionFilter",
    "SensitiveDataFilter",
    "mask_sensitive_data",
    "sanitize_value",
    "setup_structured_logging",
]
