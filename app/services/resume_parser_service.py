"""Resume Parser Service — LLM-powered structured extraction from resume text.

Uses the LLM to extract structured candidate profiles with regex as supplementary
validation for contact details (email, phone, URLs).

NO hardcoded data. Every field is extracted from the actual resume content.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import settings
from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)


class ResumeParserService:
    """AI-powered resume parser extracting structured entities from raw text."""

    def __init__(self) -> None:
        self._llm = get_llm_client()

    async def parse_resume(self, raw_text: str) -> dict[str, Any]:
        """Parse raw resume text into structured dictionary using LLM.

        Primary extraction via LLM with regex-based validation fallback
        for contact fields.
        """
        logger.info("Parsing resume text of length %s chars with LLM...", len(raw_text))

        if not raw_text or len(raw_text.strip()) < 50:
            logger.warning("Resume text too short for meaningful parsing")
            return self._empty_result()

        # 1. LLM-powered structured extraction
        llm_result = await self._extract_with_llm(raw_text)

        # 2. Regex-based validation/supplement for contact fields
        regex_data = self._extract_contact_info(raw_text)

        # 3. Merge: LLM result takes priority, regex fills gaps
        result = self._merge_results(llm_result, regex_data)

        logger.info(
            "Resume parsed: name=%s, skills=%d, experience=%.1f yrs",
            result.get("candidate_name", "Unknown"),
            len(result.get("skills", [])),
            result.get("total_experience_years", 0),
        )

        return result

    async def _extract_with_llm(self, raw_text: str) -> dict[str, Any]:
        """Use LLM to extract structured data from resume text."""
        try:
            prompt = PromptLibrary.resume_parser_user(raw_text)
            response = await self._llm.complete(
                prompt=prompt,
                system=PromptLibrary.RESUME_PARSER_SYSTEM,
                json_mode=True,
                temperature=0.1,
                num_predict=4096,
            )

            if not response:
                logger.warning("LLM returned empty response for resume parsing")
                return {}

            parsed = ResponseParser.extract_json_object(response)
            if not parsed:
                logger.warning("Failed to parse JSON from LLM resume response")
                return {}

            # Normalize into our standard schema
            return self._normalize_llm_output(parsed)

        except Exception as exc:
            logger.error("LLM resume parsing failed: %s", exc)
            return {}

    def _normalize_llm_output(self, data: dict) -> dict[str, Any]:
        """Normalize LLM output into the standard ParsedResumeSchema format."""
        # Extract skills from structured or flat format
        skills_data = data.get("skills", {})
        if isinstance(skills_data, dict):
            all_skills = []
            for category in ["programming_languages", "frameworks", "databases",
                           "cloud", "tools", "soft_skills", "domain_expertise", "other"]:
                items = skills_data.get(category, [])
                if isinstance(items, list):
                    all_skills.extend(items)
            technical_skills = []
            for category in ["programming_languages", "frameworks", "databases", "cloud", "tools"]:
                items = skills_data.get(category, [])
                if isinstance(items, list):
                    technical_skills.extend(items)
            soft_skills = skills_data.get("soft_skills", [])
        elif isinstance(skills_data, list):
            all_skills = skills_data
            technical_skills = skills_data
            soft_skills = []
        else:
            all_skills = []
            technical_skills = []
            soft_skills = []

        # Extract experience
        experience = data.get("experience", [])
        if isinstance(experience, list):
            companies = [exp.get("company", "") for exp in experience if isinstance(exp, dict) and exp.get("company")]
        else:
            companies = []

        current_company = None
        current_designation = None
        if experience and isinstance(experience, list):
            for exp in experience:
                if isinstance(exp, dict) and exp.get("is_current", False) or exp.get("end_date", "").lower() in ("present", "current", "now"):
                    current_company = exp.get("company")
                    current_designation = exp.get("designation") or exp.get("role") or exp.get("title")
                    break
            if not current_company and experience:
                first = experience[0]
                if isinstance(first, dict):
                    current_company = first.get("company")
                    current_designation = first.get("designation") or first.get("role") or first.get("title")

        # Experience years
        years_exp = data.get("years_experience", 0) or data.get("total_experience_years", 0)
        if isinstance(years_exp, str):
            try:
                years_exp = float(re.sub(r"[^\d.]", "", years_exp))
            except (ValueError, TypeError):
                years_exp = 0.0

        # Education
        education = data.get("education", [])
        if not isinstance(education, list):
            education = []
        normalized_edu = []
        for edu in education:
            if isinstance(edu, dict):
                normalized_edu.append({
                    "degree": edu.get("degree", ""),
                    "field_of_study": edu.get("field") or edu.get("field_of_study") or edu.get("major", ""),
                    "university": edu.get("institution") or edu.get("university", ""),
                    "college": edu.get("college", ""),
                    "passing_year": edu.get("graduation_year") or edu.get("passing_year"),
                    "grade": edu.get("grade"),
                })

        # Projects
        projects = data.get("projects", [])
        if not isinstance(projects, list):
            projects = []
        normalized_projects = []
        for proj in projects:
            if isinstance(proj, dict):
                normalized_projects.append({
                    "title": proj.get("name") or proj.get("title", ""),
                    "description": proj.get("description", ""),
                    "technologies": proj.get("technologies") or proj.get("tech_stack", []),
                    "url": proj.get("url"),
                })

        # Certifications
        certifications = data.get("certifications", [])
        if isinstance(certifications, list):
            cert_names = []
            for cert in certifications:
                if isinstance(cert, str):
                    cert_names.append(cert)
                elif isinstance(cert, dict):
                    cert_names.append(cert.get("name", ""))
            certifications = cert_names

        return {
            "candidate_name": data.get("name") or data.get("candidate_name") or "",
            "email": data.get("email"),
            "phone": data.get("mobile") or data.get("phone"),
            "address": data.get("address") or data.get("location"),
            "linkedin": data.get("linkedin_url") or data.get("linkedin"),
            "github": data.get("github_url") or data.get("github"),
            "portfolio": data.get("portfolio_url") or data.get("portfolio"),
            "summary": data.get("summary", ""),
            "total_experience_years": float(years_exp) if years_exp else 0.0,
            "current_company": current_company,
            "previous_companies": companies[1:] if len(companies) > 1 else [],
            "current_designation": current_designation,
            "skills": all_skills,
            "technical_skills": technical_skills,
            "soft_skills": soft_skills if soft_skills else [],
            "languages": data.get("languages", []),
            "education": normalized_edu,
            "certifications": certifications,
            "projects": normalized_projects,
            "achievements": data.get("achievements", []) or data.get("awards", []) or [],
            "internships": data.get("internships", []),
            "current_salary": data.get("current_salary"),
            "expected_salary": data.get("expected_salary"),
            "notice_period_days": self._parse_notice_period(data.get("notice_period")),
            "current_location": data.get("address") or data.get("location"),
            "preferred_location": data.get("preferred_location"),
            "willing_to_relocate": data.get("willing_to_relocate"),
        }

    def _extract_contact_info(self, text: str) -> dict[str, Any]:
        """Extract contact information using regex as validation/supplement."""
        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
        phone_match = re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
        linkedin_match = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+)", text, re.IGNORECASE)
        github_match = re.search(r"(https?://(?:www\.)?github\.com/[a-zA-Z0-9_-]+)", text, re.IGNORECASE)

        return {
            "email": email_match.group(0).lower() if email_match else None,
            "phone": phone_match.group(0) if phone_match else None,
            "linkedin": linkedin_match.group(1) if linkedin_match else None,
            "github": github_match.group(1) if github_match else None,
        }

    def _merge_results(self, llm_data: dict, regex_data: dict) -> dict[str, Any]:
        """Merge LLM results with regex validation data."""
        if not llm_data:
            # LLM failed entirely — return minimal regex-based data
            return {
                **self._empty_result(),
                "email": regex_data.get("email"),
                "phone": regex_data.get("phone"),
                "linkedin": regex_data.get("linkedin"),
                "github": regex_data.get("github"),
            }

        # Use regex data to fill or validate contact fields
        for field in ["email", "phone", "linkedin", "github"]:
            if not llm_data.get(field) and regex_data.get(field):
                llm_data[field] = regex_data[field]

        return llm_data

    @staticmethod
    def _parse_notice_period(value: Any) -> int | None:
        """Parse notice period string into days."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            # Try to extract number
            match = re.search(r"(\d+)", value)
            if match:
                num = int(match.group(1))
                if "month" in value.lower():
                    return num * 30
                if "week" in value.lower():
                    return num * 7
                return num
        return None

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        """Return an empty result structure."""
        return {
            "candidate_name": "",
            "email": None,
            "phone": None,
            "address": None,
            "linkedin": None,
            "github": None,
            "portfolio": None,
            "summary": "",
            "total_experience_years": 0.0,
            "current_company": None,
            "previous_companies": [],
            "current_designation": None,
            "skills": [],
            "technical_skills": [],
            "soft_skills": [],
            "languages": [],
            "education": [],
            "certifications": [],
            "projects": [],
            "achievements": [],
            "internships": [],
            "current_salary": None,
            "expected_salary": None,
            "notice_period_days": None,
            "current_location": None,
            "preferred_location": None,
            "willing_to_relocate": None,
        }
