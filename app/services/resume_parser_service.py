"""Resume Parser Service — LLM-powered structured extraction from resume text.

Uses the LLM to extract structured candidate profiles with regex as supplementary
validation for contact details (email, phone, URLs) and anti-hallucination verification.

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
        for contact fields and anti-hallucination verification.
        """
        logger.info("Parsing resume text of length %s chars with LLM...", len(raw_text))

        if not raw_text or len(raw_text.strip()) < 30:
            logger.warning("Resume text too short for meaningful parsing")
            return self._empty_result()

        # 1. LLM-powered structured extraction
        llm_result = await self._extract_with_llm(raw_text)

        # 2. Regex-based validation/supplement for contact fields
        regex_data = self._extract_contact_info(raw_text)

        # 3. Merge: LLM result takes priority, regex fills gaps
        result = self._merge_results(llm_result, regex_data)

        # 4. Anti-hallucination verification against raw text
        result = self._verify_anti_hallucination(result, raw_text)

        # 5. Compute parsing confidence score
        result["parsing_confidence"] = self._calculate_confidence(result, raw_text)

        logger.info(
            "Resume parsed: name=%s, skills=%d, experience=%.1f yrs, confidence=%.2f",
            result.get("candidate_name", "Unknown"),
            len(result.get("skills", [])),
            result.get("total_experience_years", 0),
            result.get("parsing_confidence", 0.0),
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
            return self._normalize_llm_output(parsed, raw_text)

        except Exception as exc:
            logger.error("LLM resume parsing failed: %s", exc)
            return {}

    def _normalize_llm_output(self, data: dict, raw_text: str = "") -> dict[str, Any]:
        """Normalize LLM output into the standard ParsedResumeSchema format."""
        # Check nested "candidate" block if present
        candidate_block = data.get("candidate") if isinstance(data.get("candidate"), dict) else {}

        name = (
            candidate_block.get("full_name")
            or candidate_block.get("name")
            or data.get("name")
            or data.get("candidate_name")
            or ""
        )
        email = candidate_block.get("email") or data.get("email")
        phone = candidate_block.get("phone") or candidate_block.get("mobile") or data.get("mobile") or data.get("phone")
        location = (
            candidate_block.get("location")
            or candidate_block.get("address")
            or data.get("address")
            or data.get("location")
            or data.get("current_location")
        )
        linkedin = candidate_block.get("linkedin_url") or candidate_block.get("linkedin") or data.get("linkedin_url") or data.get("linkedin")
        github = candidate_block.get("github_url") or candidate_block.get("github") or data.get("github_url") or data.get("github")
        portfolio = candidate_block.get("portfolio_url") or candidate_block.get("portfolio") or data.get("portfolio_url") or data.get("portfolio")

        # Extract skills from structured or flat format
        skills_data = data.get("skills", {})
        if isinstance(skills_data, dict):
            all_skills = []
            for category in ["programming_languages", "frameworks", "databases",
                           "cloud", "tools", "soft_skills", "domain_expertise", "other"]:
                items = skills_data.get(category, [])
                if isinstance(items, list):
                    all_skills.extend([str(i).strip() for i in items if i])
            technical_skills = []
            for category in ["programming_languages", "frameworks", "databases", "cloud", "tools"]:
                items = skills_data.get(category, [])
                if isinstance(items, list):
                    technical_skills.extend([str(i).strip() for i in items if i])
            soft_skills = [str(i).strip() for i in skills_data.get("soft_skills", []) if i] if isinstance(skills_data.get("soft_skills"), list) else []
        elif isinstance(skills_data, list):
            all_skills = [str(i).strip() for i in skills_data if i]
            technical_skills = [str(i).strip() for i in (data.get("technical_skills") or skills_data) if i]
            soft_skills = [str(i).strip() for i in (data.get("soft_skills") or []) if i]
        else:
            all_skills = []
            technical_skills = []
            soft_skills = []

        # Extract work experience
        raw_experience = data.get("work_experience") or data.get("experience") or data.get("work_history") or []
        normalized_exp = []
        companies = []

        if isinstance(raw_experience, list):
            for exp in raw_experience:
                if isinstance(exp, dict):
                    comp = exp.get("company") or ""
                    if comp:
                        companies.append(comp)
                    desig = exp.get("designation") or exp.get("role") or exp.get("title") or ""
                    is_curr = exp.get("is_current", False)
                    end_d = exp.get("end_date") or ""
                    if str(end_d).lower() in ("present", "current", "now", "ongoing"):
                        is_curr = True

                    responsibilities = exp.get("responsibilities") or []
                    if isinstance(responsibilities, str):
                        responsibilities = [r.strip() for r in responsibilities.split("\n") if r.strip()]
                    elif not isinstance(responsibilities, list):
                        responsibilities = []

                    technologies = exp.get("technologies") or exp.get("tech_stack") or []
                    if isinstance(technologies, str):
                        technologies = [t.strip() for t in technologies.split(",") if t.strip()]
                    elif not isinstance(technologies, list):
                        technologies = []

                    normalized_exp.append({
                        "company": comp,
                        "designation": desig,
                        "location": exp.get("location"),
                        "start_date": exp.get("start_date"),
                        "end_date": end_d,
                        "duration_months": exp.get("duration_months"),
                        "is_current": is_curr,
                        "description": exp.get("description") or "",
                        "responsibilities": responsibilities,
                        "technologies": technologies,
                    })

        current_company = data.get("current_company")
        current_designation = data.get("current_designation")
        if not current_company and normalized_exp:
            for exp in normalized_exp:
                if exp.get("is_current"):
                    current_company = exp.get("company")
                    current_designation = exp.get("designation")
                    break
            if not current_company and normalized_exp:
                current_company = normalized_exp[0].get("company")
                current_designation = normalized_exp[0].get("designation")

        # Experience years
        years_exp = data.get("years_experience", 0) or data.get("total_experience_years", 0)
        if isinstance(years_exp, str):
            try:
                years_exp = float(re.sub(r"[^\d.]", "", years_exp))
            except (ValueError, TypeError):
                years_exp = 0.0

        # Education
        raw_education = data.get("education", [])
        if not isinstance(raw_education, list):
            raw_education = []
        normalized_edu = []
        for edu in raw_education:
            if isinstance(edu, dict):
                normalized_edu.append({
                    "degree": edu.get("degree", ""),
                    "field_of_study": edu.get("field") or edu.get("field_of_study") or edu.get("major", ""),
                    "university": edu.get("institution") or edu.get("university", ""),
                    "college": edu.get("college", ""),
                    "location": edu.get("location"),
                    "start_date": edu.get("start_date"),
                    "end_date": edu.get("end_date"),
                    "passing_year": self._parse_year(edu.get("graduation_year") or edu.get("passing_year") or edu.get("end_date")),
                    "grade": edu.get("grade"),
                })

        # Projects
        raw_projects = data.get("projects", [])
        if not isinstance(raw_projects, list):
            raw_projects = []
        normalized_projects = []
        for proj in raw_projects:
            if isinstance(proj, dict):
                techs = proj.get("technologies") or proj.get("tech_stack", [])
                if isinstance(techs, str):
                    techs = [t.strip() for t in techs.split(",") if t.strip()]
                normalized_projects.append({
                    "title": proj.get("name") or proj.get("title", ""),
                    "description": proj.get("description", ""),
                    "technologies": techs if isinstance(techs, list) else [],
                    "url": proj.get("url"),
                })

        # Certifications
        raw_certs = data.get("certifications", [])
        certifications = []
        if isinstance(raw_certs, list):
            for cert in raw_certs:
                if isinstance(cert, str) and cert.strip():
                    certifications.append(cert.strip())
                elif isinstance(cert, dict) and cert.get("name"):
                    certifications.append(cert.get("name").strip())

        # Highest qualification
        highest_qualification = data.get("highest_qualification")
        if not highest_qualification and normalized_edu:
            degrees = [e["degree"] for e in normalized_edu if e.get("degree")]
            if degrees:
                highest_qualification = degrees[0]

        return {
            "candidate_name": name,
            "email": email,
            "phone": phone,
            "address": location,
            "linkedin": linkedin,
            "github": github,
            "portfolio": portfolio,
            "summary": data.get("professional_summary") or data.get("summary", ""),
            "total_experience_years": float(years_exp) if years_exp else 0.0,
            "current_company": current_company,
            "previous_companies": companies[1:] if len(companies) > 1 else [],
            "current_designation": current_designation,
            "skills": all_skills,
            "raw_skills": all_skills,
            "technical_skills": technical_skills,
            "soft_skills": soft_skills,
            "languages": [str(l).strip() for l in data.get("languages", []) if l] if isinstance(data.get("languages"), list) else [],
            "education": normalized_edu,
            "work_history": normalized_exp,
            "experience": normalized_exp,
            "certifications": certifications,
            "projects": normalized_projects,
            "achievements": data.get("achievements", []) or data.get("awards", []) or [],
            "internships": data.get("internships", []) if isinstance(data.get("internships"), list) else [],
            "current_salary": data.get("current_salary"),
            "expected_salary": data.get("expected_salary"),
            "notice_period": data.get("notice_period"),
            "notice_period_days": self._parse_notice_period(data.get("notice_period")),
            "highest_qualification": highest_qualification,
            "current_location": location,
            "preferred_location": data.get("preferred_location"),
            "willing_to_relocate": data.get("willing_to_relocate"),
        }

    def _extract_contact_info(self, text: str) -> dict[str, Any]:
        """Extract contact information using regex as validation/supplement."""
        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
        phone_match = re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
        linkedin_match = re.search(r"(https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+)", text, re.IGNORECASE)
        github_match = re.search(r"(https?://(?:www\.)?github\.com/[a-zA-Z0-9_-]+)", text, re.IGNORECASE)
        portfolio_match = re.search(r"(https?://(?:www\.)?[a-zA-Z0-9_-]+\.(?:io|me|dev|app|com)/?[a-zA-Z0-9_-]*)", text, re.IGNORECASE)

        return {
            "email": email_match.group(0).lower() if email_match else None,
            "phone": phone_match.group(0) if phone_match else None,
            "linkedin": linkedin_match.group(1) if linkedin_match else None,
            "github": github_match.group(1) if github_match else None,
            "portfolio": portfolio_match.group(1) if portfolio_match else None,
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
                "portfolio": regex_data.get("portfolio"),
            }

        # Use regex data to fill contact fields if missing from LLM
        for field in ["email", "phone", "linkedin", "github", "portfolio"]:
            if not llm_data.get(field) and regex_data.get(field):
                llm_data[field] = regex_data[field]

        return llm_data

    def _verify_anti_hallucination(self, data: dict[str, Any], raw_text: str) -> dict[str, Any]:
        """Verify that contact details and critical entities are grounded in the raw resume text."""
        raw_lower = raw_text.lower()

        # 1. Verify email
        email = data.get("email")
        if email and email.lower() not in raw_lower:
            # Re-check via regex in raw text
            email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_text)
            data["email"] = email_match.group(0).lower() if email_match else None

        # 2. Verify phone
        phone = data.get("phone")
        if phone:
            digits = re.sub(r"[^\d]", "", phone)
            raw_digits = re.sub(r"[^\d]", "", raw_text)
            if digits and len(digits) >= 7 and digits not in raw_digits and digits[-7:] not in raw_digits:
                phone_match = re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text)
                data["phone"] = phone_match.group(0) if phone_match else None

        # 3. Clean empty strings to None for contact fields
        for field in ["email", "phone", "linkedin", "github", "portfolio", "address", "current_location"]:
            val = data.get(field)
            if isinstance(val, str) and not val.strip():
                data[field] = None

        return data

    def _calculate_confidence(self, data: dict[str, Any], raw_text: str) -> float:
        """Calculate overall parsing confidence score (0.0 to 1.0)."""
        score = 0.50  # Base confidence for non-empty text

        if data.get("candidate_name") and len(data["candidate_name"].strip()) >= 3:
            score += 0.15
        if data.get("email"):
            score += 0.10
        if data.get("phone"):
            score += 0.05
        if data.get("skills") and len(data["skills"]) >= 3:
            score += 0.10
        if data.get("education") and len(data["education"]) > 0:
            score += 0.05
        if data.get("work_history") and len(data["work_history"]) > 0:
            score += 0.05

        return min(round(score, 2), 0.99)

    @staticmethod
    def _parse_year(value: Any) -> int | None:
        """Parse year string or int into integer."""
        if not value:
            return None
        if isinstance(value, int):
            return value if 1950 <= value <= 2035 else None
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value))
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_notice_period(value: Any) -> int | None:
        """Parse notice period string into days."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
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
            "raw_skills": [],
            "technical_skills": [],
            "soft_skills": [],
            "languages": [],
            "education": [],
            "work_history": [],
            "experience": [],
            "certifications": [],
            "projects": [],
            "achievements": [],
            "internships": [],
            "current_salary": None,
            "expected_salary": None,
            "notice_period": None,
            "notice_period_days": None,
            "highest_qualification": None,
            "current_location": None,
            "preferred_location": None,
            "willing_to_relocate": None,
            "parsing_confidence": 0.0,
        }

