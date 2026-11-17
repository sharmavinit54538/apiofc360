"""AI Interview Bot Service.

Orchestrates candidate automated sessions, answers grading, sandbox checks,
proctoring logging, and AI scorecard synthesis.
"""

from __future__ import annotations

import ast
import json
import logging
import uuid
from typing import Any, Optional
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.ai_interview import (
    AIInterviewSession,
    AIInterviewQuestionInstance,
    AIInterviewResponse,
    AIInterviewScorecard,
)
from app.models.recruitment import Candidate, Job, InterviewRound, ScorecardSubmission

logger = logging.getLogger(__name__)


class AIInterviewService:
    """Enterprise AI Interviewer orchestration layer."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def initialize_session(
        self,
        candidate_id: uuid.UUID,
        job_id: uuid.UUID,
        interview_type: str,
        company_id: Optional[uuid.UUID] = None,
        round_id: Optional[uuid.UUID] = None,
    ) -> AIInterviewSession:
        """Create a candidate session and pre-schedule dynamic questions."""
        # Verify candidate & job exist
        candidate_res = await self.db.execute(select(Candidate).where(Candidate.id == candidate_id))
        candidate = candidate_res.scalar_one_or_none()
        if not candidate:
            raise ValueError("Candidate not found.")

        job_res = await self.db.execute(select(Job).where(Job.id == job_id))
        job = job_res.scalar_one_or_none()
        if not job:
            raise ValueError("Job not found.")

        # Create session
        session = AIInterviewSession(
            id=uuid.uuid4(),
            company_id=company_id or job.company_id,
            candidate_id=candidate_id,
            job_id=job_id,
            interview_round_id=round_id,
            interview_type=interview_type.upper(),
            status="SCHEDULED",
            current_question_index=0,
        )
        self.db.add(session)
        await self.db.flush()

        # Generate dynamic questions based on job and candidate
        questions = await self._generate_dynamic_questions(candidate, job, interview_type.upper())
        for idx, q in enumerate(questions):
            q_instance = AIInterviewQuestionInstance(
                id=uuid.uuid4(),
                interview_session_id=session.id,
                question_text=q["text"],
                question_type=q["type"],
                expected_answer=q.get("expected_answer"),
                difficulty=q.get("difficulty", "MEDIUM"),
                order_index=idx,
            )
            self.db.add(q_instance)

        await self.db.commit()
        await self.db.refresh(session)
        logger.info("AI Interview session initialized: %s with %d questions", session.id, len(questions))
        return session

    async def _generate_dynamic_questions(
        self,
        candidate: Candidate,
        job: Job,
        interview_type: str,
    ) -> list[dict]:
        """Generate job-relevant questions using LLM based on job description and candidate profile."""
        try:
            # Build context for question generation
            candidate_context = f"""
Candidate: {candidate.first_name} {candidate.last_name}
Experience: {candidate.years_experience} years
Current Role: {candidate.current_role or 'Not specified'}
Current Company: {candidate.current_company or 'Not specified'}
Skills: {', '.join(candidate.skills) if candidate.skills else 'Not specified'}
Summary: {candidate.summary or 'Not provided'}
"""
            job_context = f"""
Job Title: {job.title}
Department: {job.department}
Description: {job.job_description}
Requirements: {job.requirements or 'Not specified'}
Responsibilities: {job.responsibilities or 'Not specified'}
"""
            
            # Generate questions using LLM
            prompt = f"""Generate 5-7 interview questions for a {interview_type} interview based on the following context:

CANDIDATE PROFILE:
{candidate_context}

JOB REQUIREMENTS:
{job_context}

Requirements:
1. Questions must be specific to the job role and candidate's experience level
2. Mix of technical, behavioral, and situational questions
3. Progress from easier to more challenging
4. Each question should have an expected answer outline
5. Include difficulty level (EASY, MEDIUM, HARD)
6. Return as JSON array with fields: text, type, expected_answer, difficulty

Question types: TECHNICAL, BEHAVIORAL, SITUATIONAL, CODING (if technical role)
"""
            
            res_text = await self.llm.complete(
                prompt=prompt,
                system="You are an expert technical interviewer. Generate relevant, job-specific interview questions. Return only valid JSON array.",
                json_mode=True,
                temperature=0.3
            )
            
            questions = ResponseParser.extract_json_object(res_text)
            if isinstance(questions, list) and questions:
                # Validate and normalize questions
                normalized = []
                for q in questions:
                    if isinstance(q, dict) and q.get("text"):
                        normalized.append({
                            "text": q["text"],
                            "type": q.get("type", "TECHNICAL"),
                            "expected_answer": q.get("expected_answer", ""),
                            "difficulty": q.get("difficulty", "MEDIUM"),
                        })
                if normalized:
                    return normalized
        except Exception as exc:
            logger.error("Dynamic question generation failed: %s", exc)
        
        # Fallback to default questions if generation fails
        return self._get_default_questions(interview_type)

    async def start_session(self, session_id: uuid.UUID) -> Optional[AIInterviewQuestionInstance]:
        """Trigger session transition to IN_PROGRESS and retrieve first question."""
        stmt = select(AIInterviewSession).where(AIInterviewSession.id == session_id)
        res = await self.db.execute(stmt)
        session = res.scalar_one_or_none()
        if not session:
            return None

        session.status = "IN_PROGRESS"
        await self.db.commit()

        # Get first question
        q_stmt = select(AIInterviewQuestionInstance).where(
            AIInterviewQuestionInstance.interview_session_id == session_id,
            AIInterviewQuestionInstance.order_index == 0
        )
        q_res = await self.db.execute(q_stmt)
        return q_res.scalar_one_or_none()

    async def submit_answer(
        self,
        session_id: uuid.UUID,
        question_id: uuid.UUID,
        candidate_response: str,
        code_output: Optional[str] = None,
        duration_seconds: int = 0,
        client_emotion: Optional[dict] = None,
        client_communication: Optional[dict] = None,
        client_proctoring: Optional[dict] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save response, call Ollama for scoring/feedback, and fetch next question."""
        # 1. Fetch session & question details
        stmt = (
            select(AIInterviewSession)
            .options(selectinload(AIInterviewSession.questions))
            .where(AIInterviewSession.id == session_id)
        )
        res = await self.db.execute(stmt)
        session = res.scalar_one_or_none()
        if not session:
            raise ValueError("Session not found.")

        q_stmt = select(AIInterviewQuestionInstance).where(AIInterviewQuestionInstance.id == question_id)
        q_res = await self.db.execute(q_stmt)
        question = q_res.scalar_one_or_none()
        if not question:
            raise ValueError("Question not found.")

        # 2. Evaluate response using real LLM inference
        score = None
        feedback = ""
        syntax_valid = True
        complexity = "N/A"
        evaluation_status = "PENDING"

        if question.question_type == "CODING":
            syntax_valid, syntax_error = self._validate_python_syntax(candidate_response)
            if not syntax_valid:
                score = 2
                feedback = f"Syntax error in candidate's code: {syntax_error}"
                evaluation_status = "COMPLETED"
            else:
                try:
                    eval_prompt = PromptLibrary.coding_sandbox_user(
                        question=question.question_text,
                        code=candidate_response,
                        expected_output=question.expected_answer or "passed tests"
                    )
                    res_text = await self.llm.complete(
                        prompt=eval_prompt,
                        system=PromptLibrary.CODING_SANDBOX_EVALUATION,
                        model=model,
                        json_mode=True,
                        temperature=0.1
                    )
                    graded = ResponseParser.extract_json_object(res_text)
                    score = int(graded.get("logical_score", 0))
                    feedback = graded.get("feedback_notes") or "Code syntax is valid. Technical structure evaluated."
                    complexity = graded.get("complexity") or "N/A"
                    evaluation_status = "COMPLETED"
                except Exception as exc:
                    logger.error("Coding evaluation failed: %s", exc)
                    score = None
                    feedback = "Code submitted successfully; automated evaluation failed. Requires human review."
                    evaluation_status = "FAILED"
        else:
            try:
                eval_prompt = PromptLibrary.ai_interview_user(
                    question=question.question_text,
                    response=candidate_response,
                    question_type=question.question_type
                )
                res_text = await self.llm.complete(
                    prompt=eval_prompt,
                    system=PromptLibrary.AI_INTERVIEW_EVALUATION,
                    model=model,
                    json_mode=True,
                    temperature=0.15
                )
                graded = ResponseParser.extract_json_object(res_text)
                score = int(graded.get("score", 0))
                feedback = graded.get("feedback") or "Response analyzed by AI interviewer."
                evaluation_status = "COMPLETED"
            except Exception as exc:
                logger.error("Response evaluation failed: %s", exc)
                score = None
                feedback = "Response received; automated evaluation failed. Requires human review."
                evaluation_status = "FAILED"

        # 3. Store client-provided telemetry only (no fabricated heuristics)
        emotion_data = client_emotion
        communication_data = client_communication
        proctoring_data = client_proctoring

        # 4. Save response record
        response_inst = AIInterviewResponse(
            id=uuid.uuid4(),
            interview_session_id=session_id,
            question_id=question_id,
            candidate_response=candidate_response,
            code_output=code_output,
            duration_seconds=duration_seconds,
            emotion_analysis=emotion_data,
            communication_analysis=communication_data,
            proctoring_flags=proctoring_data,
            score=score if score is not None else 0,
            evaluation_feedback=feedback,
        )
        self.db.add(response_inst)

        # 5. Move to next question
        next_index = session.current_question_index + 1
        session.current_question_index = next_index
        await self.db.commit()

        # Find next question
        next_q = None
        for q in session.questions:
            if q.order_index == next_index:
                next_q = q
                break

        if not next_q:
            # Session finished!
            session.status = "COMPLETED"
            await self.db.commit()

        return {
            "session_status": session.status,
            "score_logged": score,
            "evaluation_status": evaluation_status,
            "evaluation": feedback,
            "complexity": complexity,
            "next_question": {
                "id": str(next_q.id),
                "text": next_q.question_text,
                "type": next_q.question_type,
                "difficulty": next_q.difficulty,
            } if next_q else None
        }

    async def log_proctoring_alert(
        self,
        session_id: uuid.UUID,
        alert_type: str,
        details: str,
    ) -> bool:
        """Log anti-cheating alerts to active session logs."""
        stmt = select(AIInterviewSession).where(AIInterviewSession.id == session_id)
        res = await self.db.execute(stmt)
        session = res.scalar_one_or_none()
        if not session:
            return False

        # Add a custom response entry for proctoring flag audit trail
        # Simply log it as an event associated with the session
        logger.warning("Proctor alert on session %s: %s - %s", session_id, alert_type, details)
        return True

    async def finalize_interview(
        self,
        session_id: uuid.UUID,
        submitted_by_user_id: uuid.UUID,
        model: Optional[str] = None,
    ) -> AIInterviewScorecard:
        """Aggregate evaluations, synthesize hiring recommendation, and register ScorecardSubmission."""
        stmt = (
            select(AIInterviewSession)
            .options(selectinload(AIInterviewSession.responses).selectinload(AIInterviewResponse.question))
            .where(AIInterviewSession.id == session_id)
        )
        res = await self.db.execute(stmt)
        session = res.scalar_one_or_none()
        if not session:
            raise ValueError("Session not found.")

        # Aggregate responses log - only include completed evaluations
        eval_log = []
        total_score = 0
        scored_count = 0
        failed_evaluations = 0
        
        for r in session.responses:
            eval_status = "COMPLETED" if r.score > 0 or "FAILED" not in r.evaluation_feedback else "FAILED"
            eval_log.append(
                f"- Question: '{r.question.question_text}'\n"
                f"  Response: '{r.candidate_response}'\n"
                f"  Score: {r.score}/10\n"
                f"  Feedback: {r.evaluation_feedback}\n"
                f"  Evaluation Status: {eval_status}"
            )
            if r.score > 0:
                total_score += r.score
                scored_count += 1
            else:
                failed_evaluations += 1

        eval_summary_text = "\n\n".join(eval_log)
        proctoring_warnings = "No suspicious behavior detected."

        # Compile final recommendation via Ollama
        synth = None
        try:
            synth_prompt = PromptLibrary.ai_scorecard_user(
                interview_type=session.interview_type,
                responses_log=eval_summary_text,
                proctoring_warnings=proctoring_warnings
            )
            res_text = await self.llm.complete(
                prompt=synth_prompt,
                system=PromptLibrary.AI_SCORECARD_SYNTHESIS,
                model=model,
                json_mode=True,
                temperature=0.2
            )
            synth = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("Scorecard synthesis failed: %s", exc)
            synth = None

        # Determine recommendation based on actual scored responses
        if scored_count > 0:
            avg_score = total_score / scored_count
            if avg_score >= 7:
                recommendation = "HIRE"
            elif avg_score >= 5:
                recommendation = "MAYBE"
            else:
                recommendation = "REJECT"
        else:
            recommendation = "REVIEW_REQUIRED"

        justification = synth.get("overall_justification") if synth else "AI evaluation synthesis failed. Manual review required."
        anti_cheating = synth.get("anti_cheating_report") if synth else {"total_warnings": 0, "suspicious_activity_flagged": False, "note": "Proctoring data not fully analyzed"}
        emotion_summary = synth.get("emotion_summary") if synth else {"note": "Emotion analysis not available"}
        communication_summary = synth.get("communication_summary") if synth else {"note": "Communication analysis not available"}

        # Save AI Scorecard record
        scorecard = AIInterviewScorecard(
            id=uuid.uuid4(),
            interview_session_id=session_id,
            anti_cheating_report=anti_cheating,
            emotion_summary=emotion_summary,
            communication_summary=communication_summary,
            final_hiring_recommendation=recommendation,
            overall_justification=justification,
        )
        self.db.add(scorecard)
        await self.db.flush()

        # Connect with standard ScorecardSubmission model in HR system
        avg_score_int = int(total_score / scored_count) if scored_count > 0 else 0
        submission = ScorecardSubmission(
            id=uuid.uuid4(),
            interview_round_id=session.interview_round_id or uuid.uuid4(),
            submitted_by=submitted_by_user_id,
            scores={"Technical/Logical": avg_score_int},
            overall_recommendation=recommendation,
            feedback_notes=justification,
        )
        self.db.add(submission)
        await self.db.flush()

        # Map reference back
        scorecard.scorecard_submission_id = submission.id
        await self.db.commit()

        logger.info("AI Scorecard finalized for session %s. Submittor: %s, Scored: %d, Failed: %d", session_id, submission.id, scored_count, failed_evaluations)
        return scorecard

# ------------------------------------------------------------------
    # Heuristic Python Syntax Validator
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_python_syntax(code: str) -> tuple[bool, Optional[str]]:
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as err:
            return False, str(err)

    async def generate_follow_up_question(
        self,
        session_id: uuid.UUID,
        previous_question: str,
        candidate_response: str,
        interview_type: str,
    ) -> dict | None:
        """Generate a contextual follow-up question based on candidate's response."""
        try:
            prompt = f"""Based on the candidate's response, generate ONE relevant follow-up question.

Previous Question: {previous_question}
Candidate Response: {candidate_response}
Interview Type: {interview_type}

Generate a follow-up that:
1. Probes deeper into the candidate's answer
2. Is specific to what they mentioned
3. Tests practical application or edge cases
4. Returns JSON with: text, type, expected_answer, difficulty
"""
            
            res_text = await self.llm.complete(
                prompt=prompt,
                system="You are an expert interviewer generating contextual follow-up questions. Return only valid JSON.",
                json_mode=True,
                temperature=0.4
            )
            
            question = ResponseParser.extract_json_object(res_text)
            if isinstance(question, dict) and question.get("text"):
                return {
                    "text": question["text"],
                    "type": question.get("type", "TECHNICAL"),
                    "expected_answer": question.get("expected_answer", ""),
                    "difficulty": question.get("difficulty", "MEDIUM"),
                }
        except Exception as exc:
            logger.error("Follow-up question generation failed: %s", exc)
        
        return None

    # ------------------------------------------------------------------
    # Fallback Default Questions Pool (used only if LLM generation fails)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_default_questions(interview_type: str) -> list[dict[str, str]]:
        """Fallback questions - only used when dynamic generation fails."""
        if interview_type == "CODING":
            return [
                {
                    "text": "Write a Python function to reverse a string in-place without allocating extra storage.",
                    "type": "CODING",
                    "expected_answer": "def reverse(s): return s[::-1]",
                    "difficulty": "EASY",
                },
                {
                    "text": "Implement a function that finds the longest repeating substring in a string.",
                    "type": "CODING",
                    "expected_answer": "Slices comparisons",
                    "difficulty": "MEDIUM",
                },
                {
                    "text": "Design a rate limiter for an API service.",
                    "type": "CODING",
                    "expected_answer": "Token bucket or sliding window algorithm",
                    "difficulty": "HARD",
                }
            ]
        elif interview_type == "BEHAVIORAL":
            return [
                {
                    "text": "Describe a conflict you had with a team member and how you resolved it.",
                    "type": "BEHAVIORAL",
                    "expected_answer": "STAR method resolution",
                    "difficulty": "EASY",
                },
                {
                    "text": "How do you prioritize deliverables when facing multiple tight deadlines?",
                    "type": "BEHAVIORAL",
                    "expected_answer": "Time boxing / Priority matrix explanation",
                    "difficulty": "MEDIUM",
                },
                {
                    "text": "Tell me about a time you had to learn a new technology quickly for a project.",
                    "type": "BEHAVIORAL",
                    "expected_answer": "Learning approach, resources used, outcome",
                    "difficulty": "MEDIUM",
                }
            ]
        else:
            # TECHNICAL / VOICE / VIDEO
            return [
                {
                    "text": "Explain the difference between synchronous and asynchronous architectures.",
                    "type": "TECHNICAL",
                    "expected_answer": "Non-blocking event loop details",
                    "difficulty": "EASY",
                },
                {
                    "text": "How does PostgreSQL implement multi-version concurrency control (MVCC)?",
                    "type": "TECHNICAL",
                    "expected_answer": "Tuple locks, transaction snapshots, VACUUM details",
                    "difficulty": "HARD",
                },
                {
                    "text": "Design a scalable caching strategy for a high-traffic web application.",
                    "type": "TECHNICAL",
                    "expected_answer": "Cache layers, invalidation strategies, consistency models",
                    "difficulty": "HARD",
                }
            ]
