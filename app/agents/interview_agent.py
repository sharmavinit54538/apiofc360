"""AI Interview Agent.

Capabilities:
- Generate dynamic, candidate-specific interview questions
- Support difficulty levels: BEGINNER | INTERMEDIATE | ADVANCED | EXPERT
- Categories: Technical Knowledge, Communication, Problem Solving,
  Confidence, Leadership, Analytical Thinking, Teamwork
- Evaluate candidate answers with scoring and feedback
- Generate interview transcript, summary, scorecard, recommendation
- Detect red flags in responses
- Architecture-ready for voice and video interview sessions
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.llm.client import LLMClient, get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

logger = logging.getLogger(__name__)

VALID_DIFFICULTIES = {"BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"}
VALID_CATEGORIES = {
    "Technical Knowledge",
    "Communication",
    "Problem Solving",
    "Confidence",
    "Leadership",
    "Analytical Thinking",
    "Teamwork",
    "System Design",
    "Behavioral",
}


@dataclass
class InterviewQuestion:
    """Single interview question with metadata."""

    question: str
    category: str
    difficulty: str
    expected_answer_outline: str = ""
    scoring_criteria: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "category": self.category,
            "difficulty": self.difficulty,
            "expected_answer_outline": self.expected_answer_outline,
            "scoring_criteria": self.scoring_criteria,
            "follow_up_questions": self.follow_up_questions,
            "red_flags": self.red_flags,
        }


@dataclass
class QuestionEvaluation:
    """Evaluation result for a single interview answer."""

    question: str
    candidate_answer: str
    score: float = 0.0
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    technical_depth: str = "UNKNOWN"
    communication_clarity: str = "UNKNOWN"
    feedback: str = ""
    follow_up_needed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "candidate_answer": self.candidate_answer,
            "score": round(self.score, 4),
            "strengths": self.strengths,
            "gaps": self.gaps,
            "technical_depth": self.technical_depth,
            "communication_clarity": self.communication_clarity,
            "feedback": self.feedback,
            "follow_up_needed": self.follow_up_needed,
        }


@dataclass
class InterviewSession:
    """Complete AI interview session with transcript and scorecard."""

    session_id: str
    candidate_name: str
    position: str
    difficulty: str
    questions: list[InterviewQuestion] = field(default_factory=list)
    evaluations: list[QuestionEvaluation] = field(default_factory=list)

    # Aggregated scores (0.0 - 1.0)
    technical_knowledge_score: float = 0.0
    communication_score: float = 0.0
    problem_solving_score: float = 0.0
    leadership_score: float = 0.0
    analytical_thinking_score: float = 0.0
    teamwork_score: float = 0.0
    overall_interview_score: float = 0.0

    # Summary
    interview_summary: str = ""
    hiring_recommendation: str = "REVIEW"  # HIRE | REJECT | REVIEW | STRONG_HIRE
    red_flags: list[str] = field(default_factory=list)
    positive_highlights: list[str] = field(default_factory=list)

    # Timestamps
    started_at: str = ""
    completed_at: str = ""

    def generate_transcript(self) -> str:
        """Build a human-readable interview transcript."""
        lines = [
            f"INTERVIEW TRANSCRIPT",
            f"Candidate: {self.candidate_name}",
            f"Position: {self.position}",
            f"Difficulty: {self.difficulty}",
            f"Date: {self.started_at}",
            "=" * 60,
            "",
        ]
        for idx, (q, e) in enumerate(zip(self.questions, self.evaluations), start=1):
            lines.append(f"Q{idx} [{q.category}] — {q.question}")
            lines.append(f"A: {e.candidate_answer}")
            lines.append(f"Score: {e.score:.2f} | {e.feedback}")
            lines.append("")
        lines.append("=" * 60)
        lines.append(f"Overall Score: {self.overall_interview_score:.2f}")
        lines.append(f"Recommendation: {self.hiring_recommendation}")
        lines.append(f"Summary: {self.interview_summary}")
        return "\n".join(lines)

    def generate_scorecard(self) -> dict[str, Any]:
        """Generate structured interview scorecard."""
        return {
            "session_id": self.session_id,
            "candidate_name": self.candidate_name,
            "position": self.position,
            "difficulty": self.difficulty,
            "scores": {
                "technical_knowledge": round(self.technical_knowledge_score, 4),
                "communication": round(self.communication_score, 4),
                "problem_solving": round(self.problem_solving_score, 4),
                "leadership": round(self.leadership_score, 4),
                "analytical_thinking": round(self.analytical_thinking_score, 4),
                "teamwork": round(self.teamwork_score, 4),
                "overall": round(self.overall_interview_score, 4),
            },
            "hiring_recommendation": self.hiring_recommendation,
            "interview_summary": self.interview_summary,
            "red_flags": self.red_flags,
            "positive_highlights": self.positive_highlights,
            "question_evaluations": [e.to_dict() for e in self.evaluations],
            "transcript": self.generate_transcript(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.generate_scorecard(),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class InterviewAgent:
    """AI agent for generating and evaluating technical interviews."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or get_llm_client()

    # ------------------------------------------------------------------
    # Question Generation
    # ------------------------------------------------------------------

    async def generate_questions(
        self,
        resume_text: str,
        jd_text: str,
        difficulty: str = "INTERMEDIATE",
        num_questions: int = 10,
        categories: list[str] | None = None,
        model: str | None = None,
    ) -> list[InterviewQuestion]:
        """Generate tailored interview questions for a candidate.

        Args:
            resume_text: Candidate resume for context.
            jd_text: Job description to match questions to requirements.
            difficulty: BEGINNER | INTERMEDIATE | ADVANCED | EXPERT
            num_questions: Number of questions (max 20).
            categories: List of question categories to include.
            model: Optional Ollama model override.
        """
        difficulty = difficulty.upper()
        if difficulty not in VALID_DIFFICULTIES:
            difficulty = "INTERMEDIATE"

        num_questions = max(3, min(num_questions, 20))
        if not categories:
            categories = list(VALID_CATEGORIES)[:5]

        safe_resume = ResponseParser.sanitize_user_input(resume_text, max_length=3000)
        safe_jd = ResponseParser.sanitize_user_input(jd_text, max_length=2000)

        response = await self._llm.complete(
            prompt=PromptLibrary.interview_questions_user(
                safe_resume, safe_jd, difficulty, num_questions, categories
            ),
            system=PromptLibrary.INTERVIEW_SYSTEM,
            model=model,
            json_mode=True,
            temperature=0.4,  # More creative for questions
            num_predict=3000,
        )

        data = ResponseParser.extract_json_object(response) if response else {}
        raw_questions = data.get("questions", [])

        questions: list[InterviewQuestion] = []
        for q in raw_questions:
            if not isinstance(q, dict) or not q.get("question"):
                continue
            questions.append(InterviewQuestion(
                question=str(q.get("question", "")).strip(),
                category=str(q.get("category", "Technical Knowledge")).strip(),
                difficulty=str(q.get("difficulty", difficulty)).strip(),
                expected_answer_outline=str(q.get("expected_answer_outline", "")),
                scoring_criteria=ResponseParser.get_list(q, "scoring_criteria"),
                follow_up_questions=ResponseParser.get_list(q, "follow_up_questions"),
                red_flags=ResponseParser.get_list(q, "red_flags"),
            ))

        logger.info("Generated %d interview questions (requested %d)", len(questions), num_questions)
        return questions

    # ------------------------------------------------------------------
    # Answer Evaluation
    # ------------------------------------------------------------------

    async def evaluate_answer(
        self,
        question: str,
        candidate_answer: str,
        expected_answer: str,
        category: str = "Technical Knowledge",
        model: str | None = None,
    ) -> QuestionEvaluation:
        """Evaluate a single interview answer.

        Returns structured scoring with feedback.
        """
        safe_answer = ResponseParser.sanitize_user_input(candidate_answer, max_length=2000)

        response = await self._llm.complete(
            prompt=PromptLibrary.interview_evaluation_user(
                question, safe_answer, expected_answer, category
            ),
            system=PromptLibrary.INTERVIEW_SYSTEM,
            model=model,
            json_mode=True,
            temperature=0.2,
            num_predict=800,
        )

        data = ResponseParser.extract_json_object(response) if response else {}

        return QuestionEvaluation(
            question=question,
            candidate_answer=candidate_answer,
            score=ResponseParser.get_float(data, "score", default=0.5),
            strengths=ResponseParser.get_list(data, "strengths"),
            gaps=ResponseParser.get_list(data, "gaps"),
            technical_depth=ResponseParser.get_str(data, "technical_depth", "UNKNOWN"),
            communication_clarity=ResponseParser.get_str(data, "communication_clarity", "UNKNOWN"),
            feedback=ResponseParser.get_str(data, "feedback"),
            follow_up_needed=bool(data.get("follow_up_needed", False)),
        )

    # ------------------------------------------------------------------
    # Full Session Evaluation
    # ------------------------------------------------------------------

    async def complete_session(
        self,
        session_id: str,
        candidate_name: str,
        position: str,
        questions: list[InterviewQuestion],
        answers: list[str],
        model: str | None = None,
    ) -> InterviewSession:
        """Evaluate all answers and generate complete session scorecard.

        Args:
            questions: Generated interview questions.
            answers: Candidate's answers in same order as questions.
        """
        started_at = datetime.now(tz=timezone.utc).isoformat()

        # Pair questions with answers (handle mismatches)
        pairs = list(zip(questions, answers))
        difficulty = questions[0].difficulty if questions else "INTERMEDIATE"

        # Evaluate all answers concurrently
        semaphore = asyncio.Semaphore(5)

        async def _eval(q: InterviewQuestion, a: str) -> QuestionEvaluation:
            async with semaphore:
                return await self.evaluate_answer(
                    question=q.question,
                    candidate_answer=a,
                    expected_answer=q.expected_answer_outline,
                    category=q.category,
                    model=model,
                )

        evaluations: list[QuestionEvaluation] = await asyncio.gather(
            *[_eval(q, a) for q, a in pairs]
        )

        # Aggregate category scores
        session = InterviewSession(
            session_id=session_id,
            candidate_name=candidate_name,
            position=position,
            difficulty=difficulty,
            questions=questions,
            evaluations=evaluations,
            started_at=started_at,
        )

        self._aggregate_scores(session, evaluations)
        await self._generate_session_summary(session, model=model)

        session.completed_at = datetime.now(tz=timezone.utc).isoformat()
        return session

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_scores(
        session: InterviewSession,
        evaluations: list[QuestionEvaluation],
    ) -> None:
        """Compute dimension-level scores from question evaluations."""
        category_scores: dict[str, list[float]] = {}

        for q, e in zip(session.questions, evaluations):
            cat = q.category
            category_scores.setdefault(cat, []).append(e.score)

        def avg(vals: list[float]) -> float:
            return sum(vals) / len(vals) if vals else 0.5

        session.technical_knowledge_score = avg(category_scores.get("Technical Knowledge", [0.5]))
        session.communication_score = avg(category_scores.get("Communication", [0.5]))
        session.problem_solving_score = avg(category_scores.get("Problem Solving", [0.5]))
        session.leadership_score = avg(category_scores.get("Leadership", [0.5]))
        session.analytical_thinking_score = avg(category_scores.get("Analytical Thinking", [0.5]))
        session.teamwork_score = avg(category_scores.get("Teamwork", [0.5]))

        all_scores = [e.score for e in evaluations]
        session.overall_interview_score = avg(all_scores)

        # Aggregate red flags
        red_flags: list[str] = []
        for q, e in zip(session.questions, evaluations):
            if e.follow_up_needed:
                red_flags.append(f"Follow-up needed on: {q.question[:80]}")
            if e.score < 0.4:
                red_flags.append(f"Weak answer [{q.category}]: {q.question[:60]}")
        session.red_flags = list(set(red_flags))

        # Positive highlights
        highlights: list[str] = []
        for q, e in zip(session.questions, evaluations):
            if e.score >= 0.8 and e.strengths:
                highlights.append(e.strengths[0])
        session.positive_highlights = highlights[:5]

    async def _generate_session_summary(
        self,
        session: InterviewSession,
        model: str | None = None,
    ) -> None:
        """Generate overall summary and recommendation using LLM."""
        score = session.overall_interview_score
        if score >= 0.80:
            session.hiring_recommendation = "STRONG_HIRE"
            session.interview_summary = (
                f"Exceptional performance across all categories. "
                f"Overall score: {score:.0%}. Highly recommend for immediate hire."
            )
        elif score >= 0.65:
            session.hiring_recommendation = "HIRE"
            session.interview_summary = (
                f"Good performance with some areas for growth. "
                f"Overall score: {score:.0%}. Recommend for hire."
            )
        elif score >= 0.45:
            session.hiring_recommendation = "REVIEW"
            session.interview_summary = (
                f"Mixed performance. Overall score: {score:.0%}. "
                f"Human review of interview responses recommended."
            )
        else:
            session.hiring_recommendation = "REJECT"
            session.interview_summary = (
                f"Below expected performance threshold. "
                f"Overall score: {score:.0%}. Does not meet role requirements."
            )
