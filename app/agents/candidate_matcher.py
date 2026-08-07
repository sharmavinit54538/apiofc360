"""Candidate Matching AI Agent.

Compares a job description with a candidate resume across 10 dimensions:
- Overall Match Score
- Skill Match (keyword + semantic)
- Experience Match (years + relevance)
- Education Match (degree + field)
- Domain Match (industry vertical)
- Industry Match (company background)
- Location Match (remote/onsite/city)
- Salary Match (expectation vs range)
- Availability Score (notice period)
- AI Confidence Score

Every score includes a natural language explanation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import LLMClient, get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)

SCORE_FIELDS = [
    "overall_match_score",
    "skill_match_score",
    "experience_match_score",
    "education_match_score",
    "domain_match_score",
    "industry_match_score",
    "location_match_score",
    "salary_match_score",
    "availability_score",
    "ai_confidence_score",
]


@dataclass
class MatchResult:
    """Structured candidate-job match result."""

    # Scores (0.0 - 1.0)
    overall_match_score: float = 0.0
    skill_match_score: float = 0.0
    experience_match_score: float = 0.0
    education_match_score: float = 0.0
    domain_match_score: float = 0.0
    industry_match_score: float = 0.0
    location_match_score: float = 0.0
    salary_match_score: float = 0.0
    availability_score: float = 0.0
    ai_confidence_score: float = 0.0

    # Skill analysis
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    extra_skills: list[str] = field(default_factory=list)

    # Natural language explanations
    experience_analysis: str = ""
    education_analysis: str = ""
    skill_analysis: str = ""
    domain_analysis: str = ""
    overall_explanation: str = ""

    # Decision signals
    hiring_signals: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    recommendation: str = "REVIEW"  # SHORTLIST | REVIEW | REJECT

    # Raw LLM data
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_match_score": self.overall_match_score,
            "skill_match_score": self.skill_match_score,
            "experience_match_score": self.experience_match_score,
            "education_match_score": self.education_match_score,
            "domain_match_score": self.domain_match_score,
            "industry_match_score": self.industry_match_score,
            "location_match_score": self.location_match_score,
            "salary_match_score": self.salary_match_score,
            "availability_score": self.availability_score,
            "ai_confidence_score": self.ai_confidence_score,
            "matching_skills": self.matching_skills,
            "missing_skills": self.missing_skills,
            "extra_skills": self.extra_skills,
            "experience_analysis": self.experience_analysis,
            "education_analysis": self.education_analysis,
            "skill_analysis": self.skill_analysis,
            "domain_analysis": self.domain_analysis,
            "overall_explanation": self.overall_explanation,
            "hiring_signals": self.hiring_signals,
            "risk_factors": self.risk_factors,
            "recommendation": self.recommendation,
        }

    @property
    def is_strong_match(self) -> bool:
        return self.overall_match_score >= 0.75

    @property
    def is_disqualified(self) -> bool:
        return self.overall_match_score < 0.35


class CandidateMatcherAgent:
    """AI agent that scores candidate-job fit across 10 dimensions."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or get_llm_client()

    async def match(
        self,
        resume_text: str,
        jd_text: str,
        model: str | None = None,
        candidate_metadata: dict | None = None,
    ) -> MatchResult:
        """Generate a full multi-dimensional match score.

        Args:
            resume_text: Raw or structured candidate resume text.
            jd_text: Full job description text.
            model: Optional Ollama model override.
            candidate_metadata: Additional data (salary, notice period, location)
                                 used for rule-based score components.
        """
        # Sanitize inputs
        safe_resume = ResponseParser.sanitize_user_input(resume_text, max_length=5000)
        safe_jd = ResponseParser.sanitize_user_input(jd_text, max_length=3000)

        # LLM-based matching
        llm_result = await self._llm_match(safe_resume, safe_jd, model=model)

        # Apply rule-based corrections if metadata available
        if candidate_metadata:
            llm_result = self._apply_rule_corrections(llm_result, safe_jd, candidate_metadata)

        return llm_result

    async def match_batch(
        self,
        candidates: list[dict[str, str]],
        jd_text: str,
        model: str | None = None,
        max_concurrent: int = 5,
    ) -> list[MatchResult]:
        """Match multiple candidates against the same JD concurrently.

        Args:
            candidates: List of dicts with 'resume_text' and optionally 'metadata'.
            jd_text: Job description text.
            max_concurrent: Max concurrent LLM calls (respect Ollama limits).
        """
        import asyncio
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _bounded_match(c: dict) -> MatchResult:
            async with semaphore:
                return await self.match(
                    resume_text=c.get("resume_text", ""),
                    jd_text=jd_text,
                    model=model,
                    candidate_metadata=c.get("metadata"),
                )

        tasks = [_bounded_match(c) for c in candidates]
        return await asyncio.gather(*tasks, return_exceptions=False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _llm_match(
        self,
        resume_text: str,
        jd_text: str,
        model: str | None = None,
    ) -> MatchResult:
        """Call LLM for semantic matching scores."""
        prompt = PromptLibrary.candidate_matching_user(resume_text, jd_text)
        system = PromptLibrary.MATCHING_SYSTEM

        response = await self._llm.complete(
            prompt=prompt,
            system=system,
            model=model,
            json_mode=True,
            temperature=0.2,
            num_predict=2000,
        )

        if not response:
            logger.warning("LLM matching returned empty response")
            return MatchResult()

        data = ResponseParser.extract_json_object(response)
        if not data:
            logger.warning("Could not parse LLM matching JSON")
            return MatchResult()

        # Validate and clamp scores
        data = ResponseParser.ensure_score_fields(data, SCORE_FIELDS, default=0.5)
        data = ResponseParser.ensure_list_fields(
            data, ["matching_skills", "missing_skills", "extra_skills",
                   "hiring_signals", "risk_factors"]
        )

        # Normalize recommendation
        recommendation = ResponseParser.normalize_decision(
            data.get("recommendation", "REVIEW"),
            valid={"SHORTLIST", "REVIEW", "REJECT", "MAYBE"},
            default="REVIEW",
        )
        if recommendation == "MAYBE":
            recommendation = "REVIEW"

        return MatchResult(
            overall_match_score=data["overall_match_score"],
            skill_match_score=data["skill_match_score"],
            experience_match_score=data["experience_match_score"],
            education_match_score=data["education_match_score"],
            domain_match_score=data["domain_match_score"],
            industry_match_score=data["industry_match_score"],
            location_match_score=data["location_match_score"],
            salary_match_score=data["salary_match_score"],
            availability_score=data["availability_score"],
            ai_confidence_score=data["ai_confidence_score"],
            matching_skills=data["matching_skills"],
            missing_skills=data["missing_skills"],
            extra_skills=data["extra_skills"],
            experience_analysis=ResponseParser.get_str(data, "experience_analysis"),
            education_analysis=ResponseParser.get_str(data, "education_analysis"),
            skill_analysis=ResponseParser.get_str(data, "skill_analysis"),
            domain_analysis=ResponseParser.get_str(data, "domain_analysis"),
            overall_explanation=ResponseParser.get_str(data, "overall_explanation"),
            hiring_signals=data["hiring_signals"],
            risk_factors=data["risk_factors"],
            recommendation=recommendation,
            raw_data=data,
        )

    @staticmethod
    def _apply_rule_corrections(
        result: MatchResult,
        jd_text: str,
        metadata: dict,
    ) -> MatchResult:
        """Apply rule-based score corrections using structured metadata."""
        # Salary matching (rule-based, more reliable than LLM)
        expected_sal = metadata.get("expected_salary")
        if expected_sal and "salary" in jd_text.lower():
            # Extract min/max from JD (rough heuristic)
            import re
            numbers = re.findall(r"\d{4,6}", jd_text)
            if numbers and expected_sal:
                try:
                    jd_numbers = sorted(int(n) for n in numbers[:4])
                    exp = float(expected_sal)
                    if jd_numbers:
                        mid = (jd_numbers[0] + jd_numbers[-1]) / 2
                        diff_ratio = abs(exp - mid) / max(mid, 1)
                        # Clamp diff to score
                        salary_score = max(0.0, 1.0 - diff_ratio)
                        result.salary_match_score = salary_score
                except (ValueError, ZeroDivisionError):
                    pass

        # Availability matching (rule-based)
        notice_period = metadata.get("notice_period", "")
        if notice_period:
            # Lower notice period = higher availability score
            import re
            days_match = re.search(r"(\d+)\s*(day|week|month)", notice_period.lower())
            if days_match:
                qty = int(days_match.group(1))
                unit = days_match.group(2)
                if "month" in unit:
                    days = qty * 30
                elif "week" in unit:
                    days = qty * 7
                else:
                    days = qty
                # 0 days = 1.0, 90 days = ~0.5, 180 days = ~0.0
                result.availability_score = max(0.0, 1.0 - (days / 180))

        return result
