"""Schema normalization and validation helpers."""

from __future__ import annotations


class ValidationMixin:
    """Methods for normalizing decisions and ensuring score fields exist."""

    @staticmethod
    def ensure_score_fields(
        data: dict,
        required_score_keys: list[str],
        default: float = 0.5,
    ) -> dict:
        """Ensure all required score keys exist and are valid floats."""
        for key in required_score_keys:
            if key not in data or not isinstance(data[key], (int, float)):
                data[key] = default
            else:
                data[key] = max(0.0, min(1.0, float(data[key])))
        return data

    @staticmethod
    def ensure_list_fields(data: dict, list_keys: list[str]) -> dict:
        """Ensure all required list keys exist and contain lists."""
        for key in list_keys:
            if not isinstance(data.get(key), list):
                data[key] = []
        return data

    @staticmethod
    def normalize_decision(raw: str, valid: set[str], default: str) -> str:
        """Normalize an LLM decision string to a valid enum value."""
        candidate = raw.strip().upper().replace(" ", "_").replace("-", "_")
        if candidate in valid:
            return candidate
        # Fuzzy match
        for valid_val in valid:
            if valid_val in candidate or candidate in valid_val:
                return valid_val
        return default
