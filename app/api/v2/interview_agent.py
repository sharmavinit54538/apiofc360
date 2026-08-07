"""AI Interview Agent API v2 — Generate questions, conduct AI interviews, evaluate answers."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.agents.interview_agent import InterviewAgent, VALID_DIFFICULTIES
from app.llm.client import get_llm_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/interview", tags=["AI Interview Agent v2"])


class GenerateQuestionsRequest(BaseModel):
    resume_document_id: uuid.UUID
    job_id: uuid.UUID
    difficulty: str = Field("INTERMEDIATE", description="BEGINNER|INTERMEDIATE|ADVANCED|EXPERT")
    num_questions: int = Field(10, ge=3, le=20)
    categories: list[str] = Field(
        default_factory=lambda: ["Technical Knowledge", "Problem Solving", "Communication"],
        description="Question categories to include"
    )
    model: str | None = None


class SubmitAnswersRequest(BaseModel):
    session_id: uuid.UUID
    answers: list[str] = Field(..., description="Answers in the same order as questions")
    model: str | None = None


class EvaluateAnswerRequest(BaseModel):
    question: str
    candidate_answer: str
    expected_answer: str = ""
    category: str = "Technical Knowledge"
    model: str | None = None


@router.post(
    "/generate-questions",
    response_model=APIResponse[dict],
    summary="Generate AI interview questions for a candidate",
    description="""
Generate dynamic, candidate-specific interview questions using Ollama LLM.

Questions are tailored to:
- The candidate's specific background and experience level
- The job requirements and tech stack
- The requested difficulty level (BEGINNER → EXPERT)
- The selected question categories

Each question includes:
- Expected answer outline
- Scoring criteria
- Follow-up question suggestions
- Red flags to watch for
""",
)
async def generate_interview_questions(
    body: GenerateQuestionsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Generate tailored interview questions for a candidate."""
    from app.models.ai_recruitment import AIResumeDocument, AIRecruitmentInterviewSession
    from app.models.recruitment import Job

    # Load resume and job
    doc_res = await db.execute(
        select(AIResumeDocument).where(AIResumeDocument.id == body.resume_document_id)
    )
    doc = doc_res.scalar_one_or_none()
    if not doc or doc.parse_status != "COMPLETED":
        raise HTTPException(status_code=404, detail="Parsed resume document not found")

    job_res = await db.execute(select(Job).where(Job.id == body.job_id, Job.is_deleted == False))
    job = job_res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Generate questions
    agent = InterviewAgent(llm_client=get_llm_client())
    questions = await agent.generate_questions(
        resume_text=doc.raw_text or "",
        jd_text=job.job_description + "\n" + (job.requirements or ""),
        difficulty=body.difficulty,
        num_questions=body.num_questions,
        categories=body.categories,
        model=body.model,
    )

    # Create session record
    session = AIRecruitmentInterviewSession(
        application_id=doc.application_id or uuid.uuid4(),
        job_id=body.job_id,
        interview_type="TEXT",
        difficulty=body.difficulty,
        status="QUESTIONS_READY",
        questions=[q.to_dict() for q in questions],
        model_used=body.model,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return APIResponse[dict](
        success=True,
        message=f"Generated {len(questions)} interview questions.",
        data={
            "session_id": str(session.id),
            "difficulty": body.difficulty,
            "categories": body.categories,
            "num_questions": len(questions),
            "questions": [q.to_dict() for q in questions],
        },
        errors=None,
    )


@router.post(
    "/submit-answers",
    response_model=APIResponse[dict],
    summary="Submit candidate answers and get full evaluation",
)
async def submit_and_evaluate(
    body: SubmitAnswersRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Submit answers for an interview session and receive complete evaluation."""
    from app.models.ai_recruitment import AIRecruitmentInterviewSession
    from app.agents.interview_agent import InterviewQuestion
    from datetime import datetime, timezone

    session_res = await db.execute(
        select(AIRecruitmentInterviewSession).where(AIRecruitmentInterviewSession.id == body.session_id)
    )
    session_rec = session_res.scalar_one_or_none()
    if not session_rec:
        raise HTTPException(status_code=404, detail="Interview session not found")

    raw_questions = session_rec.questions or []
    if not raw_questions:
        raise HTTPException(status_code=422, detail="No questions found in session")

    # Reconstruct question objects
    questions = [
        InterviewQuestion(
            question=q.get("question", ""),
            category=q.get("category", "Technical Knowledge"),
            difficulty=q.get("difficulty", session_rec.difficulty),
            expected_answer_outline=q.get("expected_answer_outline", ""),
            scoring_criteria=q.get("scoring_criteria", []),
        )
        for q in raw_questions
    ]

    # Run evaluation
    agent = InterviewAgent(llm_client=get_llm_client())
    completed = await agent.complete_session(
        session_id=str(body.session_id),
        candidate_name=session_rec.application_id and "Candidate" or "Candidate",
        position="Candidate",
        questions=questions,
        answers=body.answers,
        model=body.model,
    )

    # Update session record
    from sqlalchemy import update
    await db.execute(
        update(AIRecruitmentInterviewSession)
        .where(AIRecruitmentInterviewSession.id == body.session_id)
        .values(
            status="COMPLETED",
            answers=body.answers,
            evaluations=[e.to_dict() for e in completed.evaluations],
            technical_knowledge_score=completed.technical_knowledge_score,
            communication_score=completed.communication_score,
            problem_solving_score=completed.problem_solving_score,
            leadership_score=completed.leadership_score,
            analytical_thinking_score=completed.analytical_thinking_score,
            teamwork_score=completed.teamwork_score,
            overall_interview_score=completed.overall_interview_score,
            transcript=completed.generate_transcript(),
            interview_summary=completed.interview_summary,
            hiring_recommendation=completed.hiring_recommendation,
            red_flags=completed.red_flags,
            positive_highlights=completed.positive_highlights,
            model_used=body.model,
            started_at=datetime.now(tz=timezone.utc),
            completed_at=datetime.now(tz=timezone.utc),
        )
    )
    await db.commit()

    return APIResponse[dict](
        success=True,
        message="Interview evaluation complete.",
        data=completed.generate_scorecard(),
        errors=None,
    )


@router.post(
    "/evaluate-answer",
    response_model=APIResponse[dict],
    summary="Evaluate a single interview answer",
)
async def evaluate_single_answer(
    body: EvaluateAnswerRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> APIResponse[dict]:
    """Real-time evaluation of a single interview answer."""
    agent = InterviewAgent(llm_client=get_llm_client())
    evaluation = await agent.evaluate_answer(
        question=body.question,
        candidate_answer=body.candidate_answer,
        expected_answer=body.expected_answer,
        category=body.category,
        model=body.model,
    )
    return APIResponse[dict](
        success=True,
        message="Answer evaluated.",
        data=evaluation.to_dict(),
        errors=None,
    )


@router.get(
    "/session/{session_id}",
    response_model=APIResponse[dict],
    summary="Get interview session details",
)
async def get_interview_session(
    session_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve interview session details including transcript and scorecard."""
    from app.models.ai_recruitment import AIRecruitmentInterviewSession

    result = await db.execute(
        select(AIRecruitmentInterviewSession).where(AIRecruitmentInterviewSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    return APIResponse[dict](
        success=True,
        message="Interview session retrieved.",
        data={
            "id": str(session.id),
            "status": session.status,
            "interview_type": session.interview_type,
            "difficulty": session.difficulty,
            "overall_interview_score": session.overall_interview_score,
            "technical_knowledge_score": session.technical_knowledge_score,
            "communication_score": session.communication_score,
            "problem_solving_score": session.problem_solving_score,
            "hiring_recommendation": session.hiring_recommendation,
            "interview_summary": session.interview_summary,
            "transcript": session.transcript,
            "red_flags": session.red_flags or [],
            "positive_highlights": session.positive_highlights or [],
            "created_at": session.created_at.isoformat(),
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
        errors=None,
    )
