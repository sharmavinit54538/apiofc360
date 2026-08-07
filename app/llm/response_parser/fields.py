"""Safe dictionary field getters."""

from __future__ import annotations

from typing import Any


class FieldExtractionMixin:
    """Safe retrieval of nested dictionary values with defaults and casting."""

    @staticmethod
    def get_float(data: dict, key: str, default: float = 0.0, clamp: tuple[float, float] = (0.0, 1.0)) -> float:
        """Safely extract a float score from parsed JSON, clamped to range."""
        raw = data.get(key)
        if raw is None:
            return default
        try:
            val = float(raw)
            lo, hi = clamp
            return max(lo, min(hi, val))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def get_str(data: dict, key: str, default: str = "") -> str:
        """Safely extract a string value."""
        val = data.get(key)
        if val is None:
            return default
        return str(val).strip()

    @staticmethod
    def get_list(data: dict, key: str, default: list | None = None) -> list:
        """Safely extract a list value."""
        val = data.get(key)
        if isinstance(val, list):
            return val
        if val is not None:
            return [val]
        return default if default is not None else []

    @staticmethod
    def get_dict(data: dict, key: str, default: dict | None = None) -> dict:
        """Safely extract a dict value."""
        val = data.get(key)
        if isinstance(val, dict):
            return val
        return default if default is not None else {}
