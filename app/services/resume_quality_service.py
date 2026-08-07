"""Resume Quality Service for detecting structural issues, missing fields, and formatting quality."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ResumeQualityService:
    """Service for checking resume completeness, readability, formatting, and structural issues."""

    def analyze_quality(
        self,
        raw_text: str,
        parsed_data: dict[str, Any],
        ocr_engine: str = "ocr",
    ) -> dict[str, Any]:
        """Analyze quality of resume text and parsed details."""
        issues = []
        missing_fields = []
        formatting_score = 100.0

        raw_text_clean = (raw_text or "").strip()
        is_readable = len(raw_text_clean) >= 30
        is_image_only = "image" in ocr_engine.lower() or len(raw_text_clean) < 50

        if not is_readable:
            issues.append("Unreadable or blank resume text.")
            formatting_score -= 50.0

        if not parsed_data.get("email"):
            missing_fields.append("email")
            issues.append("Missing email address.")
            formatting_score -= 15.0

        if not parsed_data.get("phone"):
            missing_fields.append("phone")
            issues.append("Missing phone number.")
            formatting_score -= 10.0

        skills = parsed_data.get("skills") or []
        if not skills:
            missing_fields.append("skills")
            issues.append("No technical or soft skills extracted.")
            formatting_score -= 20.0

        experience_years = parsed_data.get("total_experience_years") or 0.0
        education = parsed_data.get("education") or []
        if not education:
            missing_fields.append("education")
            issues.append("Missing education section.")
            formatting_score -= 10.0

        formatting_score = max(0.0, round(formatting_score, 1))
        is_valid = is_readable and (len(missing_fields) <= 2)

        return {
            "is_valid": is_valid,
            "issues": issues,
            "missing_fields": missing_fields,
            "formatting_score": formatting_score,
            "is_readable": is_readable,
            "is_image_only": is_image_only,
        }
