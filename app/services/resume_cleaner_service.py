"""Resume Cleaner Service for normalizing and deduplicating extracted candidate data."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Skill synonym mapping
SKILL_SYNONYMS: dict[str, str] = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "py": "Python",
    "python": "Python",
    "python3": "Python",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud Platform",
    "docker": "Docker",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "ml": "Machine Learning",
    "ai": "Artificial Intelligence",
}

SOFT_SKILLS_SET = {
    "communication", "teamwork", "leadership", "problem solving",
    "critical thinking", "time management", "adaptability", "collaboration",
    "creativity", "work ethic", "conflict resolution", "decision making",
}


class ResumeCleanerService:
    """Service to clean, normalize, and deduplicate extracted resume fields."""

    def clean_email(self, email: str | None) -> str | None:
        """Clean and validate email address."""
        if not email:
            return None
        cleaned = email.strip().lower()
        match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", cleaned)
        return match.group(0) if match else None

    def clean_phone(self, phone: str | None) -> str | None:
        """Clean phone number format."""
        if not phone:
            return None
        # Remove invalid text, preserve digits and leading +
        cleaned = re.sub(r"[^\d+]", "", phone.strip())
        if len(cleaned) < 7:
            return None
        return cleaned

    def clean_skills(self, skills: list[str]) -> tuple[list[str], list[str], list[str]]:
        """Normalize, deduplicate, and split skills into all_skills, technical_skills, and soft_skills."""
        if not skills:
            return [], [], []

        seen = set()
        cleaned_skills = []
        technical_skills = []
        soft_skills = []

        for skill in skills:
            if not skill or not isinstance(skill, str):
                continue
            normalized_key = skill.strip().lower()
            if not normalized_key or len(normalized_key) < 2:
                continue

            # Standardize using synonym map if available
            canonical_name = SKILL_SYNONYMS.get(normalized_key, skill.strip().title())

            if canonical_name.lower() not in seen:
                seen.add(canonical_name.lower())
                cleaned_skills.append(canonical_name)

                if canonical_name.lower() in SOFT_SKILLS_SET:
                    soft_skills.append(canonical_name)
                else:
                    technical_skills.append(canonical_name)

        return cleaned_skills, technical_skills, soft_skills

    def clean_experience_years(self, years: float | int | None, raw_text: str = "") -> float:
        """Sanitize total experience years."""
        if years is not None and isinstance(years, (int, float)) and years >= 0:
            return round(float(years), 1)

        # Fallback regex search in raw text
        if raw_text:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?)", raw_text, re.IGNORECASE)
            if match:
                try:
                    return round(float(match.group(1)), 1)
                except ValueError:
                    pass

        return 0.0

    def clean_parsed_data(self, data: dict[str, Any], raw_text: str = "") -> dict[str, Any]:
        """Normalize complete parsed resume dictionary."""
        cleaned = dict(data)

        cleaned["email"] = self.clean_email(cleaned.get("email"))
        cleaned["phone"] = self.clean_phone(cleaned.get("phone"))

        raw_skills = cleaned.get("skills") or []
        all_skills, tech_skills, soft_skills = self.clean_skills(raw_skills)

        cleaned["skills"] = all_skills
        cleaned["technical_skills"] = tech_skills or cleaned.get("technical_skills") or []
        cleaned["soft_skills"] = soft_skills or cleaned.get("soft_skills") or []

        cleaned["total_experience_years"] = self.clean_experience_years(
            cleaned.get("total_experience_years"), raw_text=raw_text
        )

        # Clean string lists (companies, languages, certifications)
        for key in ["previous_companies", "languages", "certifications", "achievements"]:
            items = cleaned.get(key) or []
            if isinstance(items, list):
                cleaned[key] = list(dict.fromkeys(item.strip() for item in items if isinstance(item, str) and item.strip()))

        return cleaned
