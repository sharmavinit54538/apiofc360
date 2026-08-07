"""Coding Assessment API v2 — Generate challenges and evaluate submissions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.agents.coding_assessment import CodingAssessmentAgent, SUPPORTED_LANGUAGES
from app.llm.client import get_llm_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coding-assessment", tags=["Coding Assessment AI v2"])


class GenerateChallengeRequest(BaseModel):
    application_id: uuid.UUID
    job_id: uuid.UUID
    language: str = Field("python", description=f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}")
    difficulty: str = Field("INTERMEDIATE", description="BEGINNER|INTERMEDIATE|ADVANCED|EXPERT")
    topic: str = Field("Data Structures", description="Algorithmic topic or domain")
    role_context: str = Field("Software Engineer", description="Role context for relevance")
    model: str | None = None


class SubmitCodeRequest(BaseModel):
    assessment_id: uuid.UUID
    candidate_code: str = Field(..., description="Candidate's code submission")
    test_results: str = Field("", description="Optional external test execution results")
    model: str | None = None


class GenerateChallengeSetRequest(BaseModel):
    application_id: uuid.UUID
    job_id: uuid.UUID
    language: str = "python"
    difficulty: str = "INTERMEDIATE"
    topics: list[str] = Field(
        default_factory=lambda: ["Data Structures", "Algorithms", "System Design"],
        max_length=5,
    )
    role_context: str = "Software Engineer"
    model: str | None = None


@router.post(
    "/generate",
    response_model=APIResponse[dict],
    summary="Generate an AI coding challenge",
    description="""
Generate a language-specific coding challenge for a candidate.

**Supported Languages:** Python, Java, JavaScript, TypeScript, C++, Go, Rust, PHP, SQL, React, Node.js

**Includes:**
- Problem statement with constraints
- Examples with explanations
- Starter code template
- Test cases (visible + hidden)
- Hints
- Time/memory limits
- Evaluation rubric (correctness 40%, complexity 35%, quality 15%, security 10%)
""",
)
async def generate_coding_challenge(
    body: GenerateChallengeRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Generate a coding challenge for a candidate."""
    from app.models.ai_recruitment import CodingAssessmentRecord

    agent = CodingAssessmentAgent(llm_client=get_llm_client())
    challenge = await agent.generate_challenge(
        language=body.language,
        difficulty=body.difficulty,
        topic=body.topic,
        role_context=body.role_context,
        model=body.model,
    )

    # Store in DB
    record = CodingAssessmentRecord(
        application_id=body.application_id,
        job_id=body.job_id,
        language=body.language,
        difficulty=body.difficulty,
        topic=body.topic,
        status="PENDING",
        challenge=challenge.to_dict(),
        time_limit_seconds=challenge.time_limit_seconds,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return APIResponse[dict](
        success=True,
        message=f"Coding challenge generated: {challenge.title}",
        data={
            "assessment_id": str(record.id),
            "status": "PENDING",
            **challenge.to_dict(),
        },
        errors=None,
    )


@router.post(
    "/generate-set",
    response_model=APIResponse[dict],
    summary="Generate a set of coding challenges across topics",
)
async def generate_challenge_set(
    body: GenerateChallengeSetRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Generate multiple challenges across different topics for a comprehensive assessment."""
    from app.models.ai_recruitment import CodingAssessmentRecord

    agent = CodingAssessmentAgent(llm_client=get_llm_client())
    challenges = await agent.generate_challenge_set(
        language=body.language,
        difficulty=body.difficulty,
        topics=body.topics,
        role_context=body.role_context,
        count=len(body.topics),
        model=body.model,
    )

    records = []
    for challenge in challenges:
        record = CodingAssessmentRecord(
            application_id=body.application_id,
            job_id=body.job_id,
            language=body.language,
            difficulty=body.difficulty,
            topic=challenge.title,
            status="PENDING",
            challenge=challenge.to_dict(),
            time_limit_seconds=challenge.time_limit_seconds,
        )
        db.add(record)
        records.append(record)

    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Generated {len(challenges)} coding challenges.",
        data={
            "assessments": [
                {"assessment_id": str(r.id), **c.to_dict()}
                for r, c in zip(records, challenges)
            ]
        },
        errors=None,
    )


@router.post(
    "/submit",
    response_model=APIResponse[dict],
    summary="Submit code and get AI evaluation",
    description="""
Submit candidate code for AI evaluation.

**Evaluation covers:**
- Correctness (40%) — based on test case results
- Time Complexity (20%) — Big-O analysis
- Space Complexity (15%) — memory usage
- Code Quality (15%) — structure, readability
- Security (10%) — vulnerability detection

Returns: scores, issues with severity, strengths, improvements, pass/fail verdict.
""",
)
async def submit_code(
    body: SubmitCodeRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Evaluate a candidate's code submission."""
    from app.models.ai_recruitment import CodingAssessmentRecord
    from sqlalchemy import update

    # Load assessment
    res = await db.execute(
        select(CodingAssessmentRecord).where(CodingAssessmentRecord.id == body.assessment_id)
    )
    record = res.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if record.status == "EVALUATED":
        raise HTTPException(status_code=422, detail="Assessment already evaluated")

    # Reconstruct challenge
    from app.agents.coding_assessment import CodingChallenge
    challenge_data = record.challenge or {}
    challenge = CodingChallenge(
        title=challenge_data.get("title", ""),
        language=record.language,
        difficulty=record.difficulty,
        problem_statement=challenge_data.get("problem_statement", ""),
        description=challenge_data.get("description", ""),
        constraints=challenge_data.get("constraints", []),
        test_cases=challenge_data.get("test_cases", []),
        evaluation_rubric=challenge_data.get("evaluation_rubric", {}),
        time_limit_seconds=record.time_limit_seconds,
    )

    # Evaluate
    agent = CodingAssessmentAgent(llm_client=get_llm_client())
    evaluation = await agent.evaluate_submission(
        challenge=challenge,
        candidate_code=body.candidate_code,
        language=record.language,
        test_results=body.test_results,
        model=body.model,
    )

    # Update record
    now = datetime.now(tz=timezone.utc)
    await db.execute(
        update(CodingAssessmentRecord)
        .where(CodingAssessmentRecord.id == body.assessment_id)
        .values(
            candidate_code=body.candidate_code,
            evaluation=evaluation.to_dict(),
            overall_score=evaluation.overall_score,
            pass_fail=evaluation.pass_fail,
            status="EVALUATED",
            submitted_at=now,
            evaluated_at=now,
        )
    )
    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Code evaluation complete. Result: {evaluation.pass_fail}",
        data={
            "assessment_id": str(body.assessment_id),
            **evaluation.to_dict(),
        },
        errors=None,
    )


@router.get(
    "/{assessment_id}",
    response_model=APIResponse[dict],
    summary="Get coding assessment details",
)
async def get_assessment(
    assessment_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve a coding assessment with challenge and evaluation."""
    from app.models.ai_recruitment import CodingAssessmentRecord

    res = await db.execute(
        select(CodingAssessmentRecord).where(CodingAssessmentRecord.id == assessment_id)
    )
    record = res.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Assessment not found")

    return APIResponse[dict](
        success=True,
        message="Assessment retrieved.",
        data={
            "id": str(record.id),
            "language": record.language,
            "difficulty": record.difficulty,
            "topic": record.topic,
            "status": record.status,
            "overall_score": record.overall_score,
            "pass_fail": record.pass_fail,
            "challenge": record.challenge,
            "evaluation": record.evaluation,
            "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
            "evaluated_at": record.evaluated_at.isoformat() if record.evaluated_at else None,
        },
        errors=None,
    )
