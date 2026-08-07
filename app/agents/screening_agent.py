"""AI Screening Agent.

Automatically screens candidates with a three-tier decision:
  SHORTLIST — strong match, recommend for next round
  REVIEW    — borderline, human review needed
  REJECT    — clear mismatch

Generates:
- Strengths list
- Weaknesses list
- Missing critical skills
- Risk analysis
- Hiring recommendation with justification
- HR notes for the hiring manager
- Suggested interview questions
- Red flags and green flags
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import LLMClient, get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser
from app.core.config import settings

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"SHORTLIST", "REVIEW", "REJECT"}


@dataclass
class ScreeningResult:
    """AI screening decision with full analysis."""

    decision: str = "REVIEW"
    confidence: float = 0.0

    # Analysis
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    risk_analysis: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    green_flags: list[str] = field(default_factory=list)

    # Recommendations
    hiring_recommendation: str = ""
    hr_notes: str = ""
    questions_to_ask: list[str] = field(default_factory=list)

    # Auto-action flags
    auto_shortlisted: bool = False
    auto_rejected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "missing_skills": self.missing_skills,
            "risk_analysis": self.risk_analysis,
            "red_flags": self.red_flags,
            "green_flags": self.green_flags,
            "hiring_recommendation": self.hiring_recommendation,
            "hr_notes": self.hr_notes,
            "questions_to_ask": self.questions_to_ask,
            "auto_shortlisted": self.auto_shortlisted,
            "auto_rejected": self.auto_rejected,
        }


class ScreeningAgent:
    """AI screening agent that auto-shortlists or rejects candidates."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or get_llm_client()
        self._shortlist_threshold = settings.AI_SCREENING_THRESHOLD
        self._rejection_threshold = settings.AI_REJECTION_THRESHOLD

    async def screen(
        self,
        resume_text: str,
        jd_text: str,
        match_score: float,
        model: str | None = None,
    ) -> ScreeningResult:
        """Screen a candidate and return a detailed decision.

        Args:
            resume_text: Raw resume text.
            jd_text: Full job description.
            match_score: Pre-computed overall match score (0.0–1.0).
            model: Optional Ollama model override.
        """
        safe_resume = ResponseParser.sanitize_user_input(resume_text, max_length=4000)
        safe_jd = ResponseParser.sanitize_user_input(jd_text, max_length=2500)

        response = await self._llm.complete(
            prompt=PromptLibrary.screening_user(safe_resume, safe_jd, match_score),
            system=PromptLibrary.SCREENING_SYSTEM,
            model=model,
            json_mode=True,
            temperature=0.2,
            num_predict=2000,
        )

        if not response:
            logger.warning("Screening LLM returned empty response — defaulting to REVIEW")
            return self._fallback_result(match_score)

        data = ResponseParser.extract_json_object(response)
        if not data:
            return self._fallback_result(match_score)

        # Normalize decision
        decision = ResponseParser.normalize_decision(
            data.get("decision", "REVIEW"), VALID_DECISIONS, default="REVIEW"
        )

        confidence = ResponseParser.get_float(data, "confidence", default=match_score)

        result = ScreeningResult(
            decision=decision,
            confidence=confidence,
            strengths=ResponseParser.get_list(data, "strengths"),
            weaknesses=ResponseParser.get_list(data, "weaknesses"),
            missing_skills=ResponseParser.get_list(data, "missing_skills"),
            risk_analysis=ResponseParser.get_list(data, "risk_analysis"),
            red_flags=ResponseParser.get_list(data, "red_flags"),
            green_flags=ResponseParser.get_list(data, "green_flags"),
            hiring_recommendation=ResponseParser.get_str(data, "hiring_recommendation"),
            hr_notes=ResponseParser.get_str(data, "hr_notes"),
            questions_to_ask=ResponseParser.get_list(data, "questions_to_ask"),
        )

        # Apply configurable thresholds for auto-actions
        if match_score >= self._shortlist_threshold and decision == "SHORTLIST":
            result.auto_shortlisted = True
        elif match_score < self._rejection_threshold and decision == "REJECT":
            result.auto_rejected = True

        return result

    async def screen_batch(
        self,
        candidates: list[dict[str, Any]],
        jd_text: str,
        model: str | None = None,
        max_concurrent: int = 5,
    ) -> list[ScreeningResult]:
        """Screen multiple candidates concurrently.

        Args:
            candidates: List of dicts with 'resume_text' and 'match_score'.
            jd_text: Full job description.
        """
        import asyncio
        semaphore = asyncio.Semaphore(max_concurrent)
        safe_jd = ResponseParser.sanitize_user_input(jd_text, max_length=2500)

        async def _bounded_screen(c: dict) -> ScreeningResult:
            async with semaphore:
                return await self.screen(
                    resume_text=c.get("resume_text", ""),
                    jd_text=safe_jd,
                    match_score=float(c.get("match_score", 0.5)),
                    model=model,
                )

        tasks = [_bounded_screen(c) for c in candidates]
        return await asyncio.gather(*tasks)

    def _fallback_result(self, match_score: float) -> ScreeningResult:
        """Return a conservative fallback when LLM fails."""
        if match_score >= self._shortlist_threshold:
            decision = "SHORTLIST"
        elif match_score < self._rejection_threshold:
            decision = "REJECT"
        else:
            decision = "REVIEW"

        return ScreeningResult(
            decision=decision,
            confidence=match_score,
            hr_notes="AI screening unavailable. Decision based on match score only.",
            hiring_recommendation=f"Score-based decision: {decision}. Manual review recommended.",
        )
