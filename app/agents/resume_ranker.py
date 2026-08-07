"""Resume Ranker AI Agent.

Ranks a batch of candidates for a given job position.
Supports Top 10, 25, 50, 100 ranking modes.

Scoring dimensions:
- Skills fit
- Experience relevance
- Project quality
- Certifications
- Semantic similarity (embedding cosine)
- Culture fit signals
- Education level
- Career growth trajectory
- Job stability (average tenure)
- Leadership indicators

Returns ranked list with per-dimension explanations.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import LLMClient, get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)

RANKING_SCORE_FIELDS = [
    "overall_score",
    "skills_score",
    "experience_score",
    "projects_score",
    "certifications_score",
    "semantic_similarity_score",
    "culture_fit_score",
    "education_score",
    "career_growth_score",
    "stability_score",
    "leadership_score",
]

VALID_TOP_N = {10, 25, 50, 100}


@dataclass
class CandidateRankScore:
    """Score for a single candidate in the ranking."""

    candidate_id: str
    candidate_name: str

    # Dimension scores (0.0 - 1.0)
    overall_score: float = 0.0
    skills_score: float = 0.0
    experience_score: float = 0.0
    projects_score: float = 0.0
    certifications_score: float = 0.0
    semantic_similarity_score: float = 0.0
    culture_fit_score: float = 0.0
    education_score: float = 0.0
    career_growth_score: float = 0.0
    stability_score: float = 0.0
    leadership_score: float = 0.0

    # Explanations
    score_explanations: dict[str, str] = field(default_factory=dict)

    # Ranking output
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "rank": self.rank,
            "overall_score": round(self.overall_score, 4),
            "skills_score": round(self.skills_score, 4),
            "experience_score": round(self.experience_score, 4),
            "projects_score": round(self.projects_score, 4),
            "certifications_score": round(self.certifications_score, 4),
            "semantic_similarity_score": round(self.semantic_similarity_score, 4),
            "culture_fit_score": round(self.culture_fit_score, 4),
            "education_score": round(self.education_score, 4),
            "career_growth_score": round(self.career_growth_score, 4),
            "stability_score": round(self.stability_score, 4),
            "leadership_score": round(self.leadership_score, 4),
            "score_explanations": self.score_explanations,
        }


@dataclass
class RankingResult:
    """Full ranking result for a job."""

    job_id: str
    top_n: int
    ranked_candidates: list[CandidateRankScore] = field(default_factory=list)
    ranking_criteria_summary: str = ""
    model_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "top_n": self.top_n,
            "total_candidates": len(self.ranked_candidates),
            "ranking_criteria_summary": self.ranking_criteria_summary,
            "model_used": self.model_used,
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
        }


class ResumeRankerAgent:
    """AI agent that ranks candidates for a job based on 10 scoring dimensions."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or get_llm_client()

    async def rank(
        self,
        candidates: list[dict[str, Any]],
        jd_text: str,
        job_id: str,
        top_n: int = 50,
        model: str | None = None,
        max_concurrent: int = 5,
    ) -> RankingResult:
        """Rank candidates for a job.

        Args:
            candidates: List of dicts with keys:
                - 'id' (str): Candidate UUID
                - 'name' (str): Candidate name
                - 'resume_text' (str): Full resume text
                - 'existing_match_score' (float, optional): Pre-computed match score
            jd_text: Full job description text.
            job_id: Job UUID for reference.
            top_n: Number of top candidates to return (10|25|50|100).
            model: Optional model override.
            max_concurrent: Max concurrent LLM scoring calls.
        """
        if top_n not in VALID_TOP_N:
            top_n = 50  # Default fallback

        safe_jd = ResponseParser.sanitize_user_input(jd_text, max_length=2500)
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _score_candidate(c: dict) -> CandidateRankScore:
            async with semaphore:
                return await self._score_single(
                    candidate_id=str(c.get("id", "")),
                    candidate_name=str(c.get("name", "Unknown")),
                    resume_text=c.get("resume_text", ""),
                    jd_text=safe_jd,
                    model=model,
                    existing_score=c.get("existing_match_score"),
                )

        tasks = [_score_candidate(c) for c in candidates]
        scores: list[CandidateRankScore] = await asyncio.gather(*tasks)

        # Sort by overall score descending
        scores.sort(key=lambda s: s.overall_score, reverse=True)

        # Assign ranks
        for idx, score in enumerate(scores[:top_n], start=1):
            score.rank = idx

        model_name = model or self._llm._default_model

        return RankingResult(
            job_id=job_id,
            top_n=top_n,
            ranked_candidates=scores[:top_n],
            ranking_criteria_summary=(
                "Ranked by: Skills Fit, Experience Relevance, Projects, Certifications, "
                "Semantic Similarity, Culture Fit, Education, Career Growth, "
                "Job Stability, and Leadership Indicators."
            ),
            model_used=model_name,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _score_single(
        self,
        candidate_id: str,
        candidate_name: str,
        resume_text: str,
        jd_text: str,
        model: str | None = None,
        existing_score: float | None = None,
    ) -> CandidateRankScore:
        """Score a single candidate with LLM + optional blending."""
        safe_resume = ResponseParser.sanitize_user_input(resume_text, max_length=3500)

        prompt = PromptLibrary.ranker_user(safe_resume, jd_text, candidate_name)
        system = PromptLibrary.RANKER_SYSTEM

        response = await self._llm.complete(
            prompt=prompt,
            system=system,
            model=model,
            json_mode=True,
            temperature=0.15,
            num_predict=1500,
        )

        data = ResponseParser.extract_json_object(response) if response else {}
        if not data:
            logger.warning("Empty/invalid LLM ranking for candidate %s", candidate_name)
            # Fallback: use existing match score if available
            fallback_score = existing_score or 0.3
            return CandidateRankScore(
                candidate_id=candidate_id,
                candidate_name=candidate_name,
                overall_score=fallback_score,
            )

        data = ResponseParser.ensure_score_fields(data, RANKING_SCORE_FIELDS, default=0.4)

        # If we have a pre-computed semantic match score, blend it
        if existing_score is not None:
            data["semantic_similarity_score"] = existing_score
            # Recalculate overall as weighted blend
            data["overall_score"] = self._weighted_overall(data)

        explanations = {}
        if isinstance(data.get("score_explanations"), dict):
            explanations = data["score_explanations"]

        return CandidateRankScore(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            overall_score=data["overall_score"],
            skills_score=data["skills_score"],
            experience_score=data["experience_score"],
            projects_score=data["projects_score"],
            certifications_score=data["certifications_score"],
            semantic_similarity_score=data["semantic_similarity_score"],
            culture_fit_score=data["culture_fit_score"],
            education_score=data["education_score"],
            career_growth_score=data["career_growth_score"],
            stability_score=data["stability_score"],
            leadership_score=data["leadership_score"],
            score_explanations=explanations,
        )

    @staticmethod
    def _weighted_overall(data: dict) -> float:
        """Compute weighted overall score from dimension scores."""
        weights = {
            "skills_score": 0.25,
            "experience_score": 0.20,
            "semantic_similarity_score": 0.15,
            "projects_score": 0.12,
            "culture_fit_score": 0.10,
            "education_score": 0.08,
            "career_growth_score": 0.05,
            "stability_score": 0.03,
            "leadership_score": 0.01,
            "certifications_score": 0.01,
        }
        total = sum(data.get(k, 0.0) * w for k, w in weights.items())
        return max(0.0, min(1.0, total))
