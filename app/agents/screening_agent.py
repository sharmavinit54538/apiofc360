"""AI Screening Agent.

Automatically screens candidates with a three-tier decision:
  SHORTLIST — strong match, recommend for next round
  REVIEW    — borderline, human review needed
  REJECT    — clear mismatch

Compliance & Safety:
- Bias stripping: strips candidate name, gender, age, nationality, photo, and pedigree elitism
- Head+tail truncation preserving critical beginning and end of resume
- Configurable timeout and retries (max 2)
- Explicit FAILED status on LLM error (no fake REVIEW/SHORTLIST)
- Auto-rejection strictly gated by AI_AUTO_REJECT_ENABLED
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import LLMClient, get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser
from app.core.config import settings

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"SHORTLIST", "REVIEW", "REJECT"}
PROMPT_VERSION = "v2.0-compliance"


def strip_biasing_metadata(resume_text: str, candidate_name: str | None = None) -> str:
    """Strip identifiable demographics, PII, and pedigree elitism to ensure fair AI evaluation.
    
    Removes:
    - Candidate name (if provided)
    - Emails and phone numbers
    - Gender indicators and explicit pronouns
    - Age and date of birth
    - Photos and headshot indicators
    - Nationality, citizenship, and marital status
    - Institutional prestige bias terms ("Ivy League", "Tier 1 College", etc.)
    """
    if not resume_text:
        return ""
    
    text = resume_text

    # 1. Candidate Name
    if candidate_name and len(candidate_name.strip()) >= 2:
        name_clean = candidate_name.strip()
        # Escape special regex characters in candidate name
        escaped_name = re.escape(name_clean)
        text = re.sub(rf"\b{escaped_name}\b", "[Candidate]", text, flags=re.IGNORECASE)
        # Also replace first name if multi-word
        parts = name_clean.split()
        if len(parts) > 1 and len(parts[0]) > 2:
            text = re.sub(rf"\b{re.escape(parts[0])}\b", "[Candidate]", text, flags=re.IGNORECASE)

    # 2. Contact info (Email, Phone)
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[Email]", text)
    text = re.sub(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[Phone]", text)

    # 3. Gender & Pronouns
    text = re.sub(r"(?i)\b(gender|sex)\s*:\s*(male|female|non-binary|transgender|other|prefer not to say)\b", "[Demographic Redacted]", text)
    text = re.sub(r"(?i)\bpronouns?\s*:\s*[^\n,]+", "[Pronouns Redacted]", text)

    # 4. Age & Date of Birth
    text = re.sub(r"(?i)\b(date\s+of\s+birth|dob|birth\s*date)\s*:\s*[^\n,;]+", "[DOB Redacted]", text)
    text = re.sub(r"(?i)\bage\s*:\s*\d{1,2}\b", "[Age Redacted]", text)
    text = re.sub(r"(?i)\bborn\s+(in|on)\s+\d{4}\b", "[DOB Redacted]", text)

    # 5. Nationality, Citizenship & Marital Status
    text = re.sub(r"(?i)\b(nationality|citizenship|visa\s+status)\s*:\s*[^\n,;]+", "[Nationality Redacted]", text)
    text = re.sub(r"(?i)\b(marital\s+status|marital)\s*:\s*[^\n,;]+", "[Marital Status Redacted]", text)

    # 6. Photos
    text = re.sub(r"(?i)\[?(photo|headshot|photograph|picture|profile\s+picture)\]?", "", text)

    # 7. College / University Pedigree Elitism
    text = re.sub(r"(?i)\b(ivy\s+league|tier\s*1\s+college|tier\s*1\s+university|premier\s+institute|pedigree\s+institution)\b", "Accredited University", text)

    return text


def truncate_head_tail(text: str, max_chars: int, label: str = "text") -> str:
    """Keep head and tail of text if it exceeds max_chars, logging the truncation."""
    if not text or len(text) <= max_chars:
        return text
    
    logger.warning(
        "Truncating %s from %d to %d chars (preserving head + tail)",
        label,
        len(text),
        max_chars,
    )
    half = (max_chars - 30) // 2
    return text[:half] + "\n...[content truncated]...\n" + text[-half:]


@dataclass
class ScreeningResult:
    """AI screening decision with full analysis and audit metadata."""

    status: str = "COMPLETED"  # COMPLETED | FAILED
    decision: str | None = "REVIEW"  # SHORTLIST | REVIEW | REJECT | None
    confidence: float = 0.0
    match_score: float = 0.0
    error_message: str | None = None

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

    # Compliance & Auditability
    model_used: str | None = None
    prompt_version: str = PROMPT_VERSION
    thresholds_used: dict[str, float] = field(default_factory=dict)
    input_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decision": self.decision,
            "confidence": self.confidence,
            "match_score": self.match_score,
            "error_message": self.error_message,
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
            "model_used": self.model_used,
            "prompt_version": self.prompt_version,
            "thresholds_used": self.thresholds_used,
            "input_hash": self.input_hash,
        }


class ScreeningAgent:
    """AI screening agent that auto-screens candidates with safety and auditability."""

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
        candidate_name: str | None = None,
    ) -> ScreeningResult:
        """Screen a candidate and return a detailed decision with compliance guarantees.

        Args:
            resume_text: Raw resume text.
            jd_text: Full job description.
            match_score: Pre-computed overall match score (0.0–1.0).
            model: Optional model override.
            candidate_name: Candidate name to strip for bias elimination.
        """
        # 1. PII and Demographic Bias Stripping
        unbiased_resume = strip_biasing_metadata(resume_text, candidate_name=candidate_name)

        # 2. Head + Tail Truncation using settings
        resume_max = settings.AI_SCREENING_RESUME_MAX_CHARS
        jd_max = settings.AI_SCREENING_JD_MAX_CHARS

        safe_resume = ResponseParser.sanitize_user_input(
            truncate_head_tail(unbiased_resume, resume_max, label="resume_text"),
            max_length=resume_max + 100,
        )
        safe_jd = ResponseParser.sanitize_user_input(
            truncate_head_tail(jd_text, jd_max, label="jd_text"),
            max_length=jd_max + 100,
        )

        # 3. Input Hash for auditability
        input_hash = hashlib.sha256((safe_resume + "::" + safe_jd).encode("utf-8")).hexdigest()
        thresholds_dict = {
            "shortlist": self._shortlist_threshold,
            "reject": self._rejection_threshold,
        }
        active_model = model or getattr(settings, "LLM_PRIMARY_PROVIDER", "ollama")

        # 4. LLM Call with timeout and retries (max 2)
        timeout_seconds = getattr(settings, "AI_SCREENING_TIMEOUT_SECONDS", 45)
        max_retries = getattr(settings, "AI_SCREENING_MAX_RETRIES", 2)
        response = None
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._llm.complete(
                        prompt=PromptLibrary.screening_user(safe_resume, safe_jd, match_score),
                        system=PromptLibrary.SCREENING_SYSTEM,
                        model=model,
                        json_mode=True,
                        temperature=0.2,
                        num_predict=2000,
                    ),
                    timeout=float(timeout_seconds),
                )
                if response:
                    break
                last_error = "Empty response from LLM"
            except asyncio.TimeoutError:
                last_error = f"Screening LLM call timed out after {timeout_seconds}s"
                logger.warning("Screening LLM attempt %d timed out", attempt + 1)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Screening LLM attempt %d failed: %s", attempt + 1, exc)

            if attempt < max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))

        if not response:
            logger.error("Screening LLM failed completely: %s — returning FAILED status", last_error)
            return ScreeningResult(
                status="FAILED",
                decision=None,
                confidence=0.0,
                match_score=match_score,
                error_message=f"LLM screening failed: {last_error}",
                model_used=active_model,
                prompt_version=PROMPT_VERSION,
                thresholds_used=thresholds_dict,
                input_hash=input_hash,
            )

        data = ResponseParser.extract_json_object(response)
        if not data:
            logger.error("Screening LLM returned invalid JSON payload: %s — returning FAILED status", response[:200])
            return ScreeningResult(
                status="FAILED",
                decision=None,
                confidence=0.0,
                match_score=match_score,
                error_message="Screening LLM response could not be parsed as valid JSON",
                model_used=active_model,
                prompt_version=PROMPT_VERSION,
                thresholds_used=thresholds_dict,
                input_hash=input_hash,
            )

        # Normalize decision
        decision = ResponseParser.normalize_decision(
            data.get("decision", "REVIEW"), VALID_DECISIONS, default="REVIEW"
        )
        confidence = ResponseParser.get_float(data, "confidence", default=match_score)

        result = ScreeningResult(
            status="COMPLETED",
            decision=decision,
            confidence=confidence,
            match_score=match_score,
            strengths=ResponseParser.get_list(data, "strengths"),
            weaknesses=ResponseParser.get_list(data, "weaknesses"),
            missing_skills=ResponseParser.get_list(data, "missing_skills"),
            risk_analysis=ResponseParser.get_list(data, "risk_analysis"),
            red_flags=ResponseParser.get_list(data, "red_flags"),
            green_flags=ResponseParser.get_list(data, "green_flags"),
            hiring_recommendation=ResponseParser.get_str(data, "hiring_recommendation"),
            hr_notes=ResponseParser.get_str(data, "hr_notes"),
            questions_to_ask=ResponseParser.get_list(data, "questions_to_ask"),
            model_used=active_model,
            prompt_version=PROMPT_VERSION,
            thresholds_used=thresholds_dict,
            input_hash=input_hash,
        )

        # Apply configurable thresholds for auto-actions
        if match_score >= self._shortlist_threshold and decision == "SHORTLIST":
            result.auto_shortlisted = True
        elif match_score < self._rejection_threshold and decision == "REJECT":
            # Compliance: AI recommends only. Auto-reject must never happen unless AI_AUTO_REJECT_ENABLED is True
            if getattr(settings, "AI_AUTO_REJECT_ENABLED", False):
                result.auto_rejected = True
            else:
                logger.info("Auto-reject suppressed: AI_AUTO_REJECT_ENABLED is false")
                result.auto_rejected = False

        return result

    async def screen_batch(
        self,
        candidates: list[dict[str, Any]],
        jd_text: str,
        model: str | None = None,
        max_concurrent: int | None = None,
    ) -> list[ScreeningResult]:
        """Screen multiple candidates concurrently with bounded semaphore and per-item fault tolerance.

        Args:
            candidates: List of dicts with 'resume_text', 'match_score', and optional 'candidate_name'.
            jd_text: Full job description.
            model: Optional model override.
            max_concurrent: Concurrency cap (defaults to setting).
        """
        concurrency = max_concurrent or getattr(settings, "AI_SCREENING_MAX_CONCURRENCY", 5)
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded_screen(c: dict) -> ScreeningResult:
            async with semaphore:
                try:
                    return await self.screen(
                        resume_text=c.get("resume_text", ""),
                        jd_text=jd_text,
                        match_score=float(c.get("match_score", 0.0)),
                        model=model,
                        candidate_name=c.get("candidate_name"),
                    )
                except Exception as exc:
                    logger.exception("Error screening candidate in batch: %s", exc)
                    return ScreeningResult(
                        status="FAILED",
                        decision=None,
                        confidence=0.0,
                        match_score=float(c.get("match_score", 0.0)),
                        error_message=f"Batch screening error: {str(exc)}",
                        model_used=model or getattr(settings, "LLM_PRIMARY_PROVIDER", "ollama"),
                        prompt_version=PROMPT_VERSION,
                        thresholds_used={
                            "shortlist": self._shortlist_threshold,
                            "reject": self._rejection_threshold,
                        },
                    )

        tasks = [_bounded_screen(c) for c in candidates]
        return await asyncio.gather(*tasks)
