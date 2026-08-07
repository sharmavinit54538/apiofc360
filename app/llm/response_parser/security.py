"""Prompt injection and sanitization security utilities."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Patterns that indicate prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?above", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a\s+)?", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a\s+)?", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN\s+mode", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
]


class SecurityMixin:
    """Methods for detecting prompt injections and sanitizing LLM user inputs."""

    @staticmethod
    def contains_injection(text: str) -> bool:
        """Return True if the text contains likely prompt injection patterns."""
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                logger.warning("Prompt injection pattern detected in user input")
                return True
        return False

    @staticmethod
    def sanitize_user_input(text: str, max_length: int = 10000) -> str:
        """Sanitize user-provided text to prevent prompt injection."""
        if not text:
            return ""
        # Remove null bytes and non-printable control chars (keep newlines/tabs)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # Truncate
        return cleaned[:max_length]
