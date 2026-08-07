"""JSON extraction from raw LLM responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Regex patterns for extracting JSON from LLM output
_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL | re.IGNORECASE,
)
_BARE_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_BARE_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class JSONExtractionMixin:
    """Methods for extracting JSON blocks and arrays from LLM response text."""

    @staticmethod
    def extract_json(text: str) -> dict[str, Any] | list[Any] | None:
        """Extract the first valid JSON object or array from LLM output."""
        if not text or not text.strip():
            return None

        # Try markdown fenced code block first
        match = _JSON_BLOCK_RE.search(text)
        if match:
            candidate = match.group(1).strip()
            parsed = JSONExtractionMixin._try_parse(candidate)
            if parsed is not None:
                return parsed

        # Try bare JSON object
        match = _BARE_OBJECT_RE.search(text)
        if match:
            parsed = JSONExtractionMixin._try_parse(match.group())
            if parsed is not None:
                return parsed

        # Try bare JSON array
        match = _BARE_ARRAY_RE.search(text)
        if match:
            parsed = JSONExtractionMixin._try_parse(match.group())
            if parsed is not None:
                return parsed

        # Try entire text
        parsed = JSONExtractionMixin._try_parse(text.strip())
        if parsed is not None:
            return parsed

        logger.warning("ResponseParser: no valid JSON found in LLM output (len=%d)", len(text))
        return None

    @staticmethod
    def extract_json_object(text: str) -> dict[str, Any]:
        """Extract JSON object, returning empty dict on failure."""
        result = JSONExtractionMixin.extract_json(text)
        if isinstance(result, dict):
            return result
        return {}

    @staticmethod
    def extract_json_array(text: str) -> list[Any]:
        """Extract JSON array, returning empty list on failure."""
        result = JSONExtractionMixin.extract_json(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # Try to find an array value inside the dict
            for val in result.values():
                if isinstance(val, list):
                    return val
        return []

    @staticmethod
    def _try_parse(text: str) -> dict[str, Any] | list[Any] | None:
        """Attempt to parse text as JSON, returning None on failure."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            fixed = JSONExtractionMixin._fix_common_json_errors(text)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _fix_common_json_errors(text: str) -> str:
        """Attempt to fix common LLM JSON formatting errors."""
        text = re.sub(r",\s*([}\]])", r"\1", text)
        text = re.sub(r"\bNone\b", "null", text)
        text = re.sub(r"\bTrue\b", "true", text)
        text = re.sub(r"\bFalse\b", "false", text)
        text = re.sub(r"//[^\n]*", "", text)
        return text
