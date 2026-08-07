"""Coding Assessment AI Agent.

Generates language-specific coding challenges and evaluates solutions.

Supported languages:
Python, Java, JavaScript, TypeScript, C++, Go, Rust, PHP, SQL, React, Node.js

Challenge generation considers:
- Candidate's role and experience level
- Relevant tech stack from resume
- Appropriate difficulty

Evaluation covers:
- Correctness (test case pass rate)
- Time complexity (Big-O analysis)
- Space complexity
- Code quality (readability, structure)
- Naming conventions
- Best practices adherence
- Security issues detection
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

SUPPORTED_LANGUAGES = {
    "python", "java", "javascript", "typescript",
    "cpp", "go", "rust", "php", "sql", "react", "nodejs",
}

DIFFICULTY_TO_NUM = {
    "BEGINNER": 1,
    "INTERMEDIATE": 2,
    "ADVANCED": 3,
    "EXPERT": 4,
}

SEVERITY_ORDER = {"ERROR": 3, "WARNING": 2, "INFO": 1}


@dataclass
class TestCase:
    """A single test case for a coding challenge."""

    input: Any
    expected_output: Any
    explanation: str = ""
    is_hidden: bool = False


@dataclass
class CodingChallenge:
    """A coding challenge specification."""

    title: str
    language: str
    difficulty: str
    description: str = ""
    problem_statement: str = ""
    constraints: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    starter_code: str = ""
    test_cases: list[dict] = field(default_factory=list)
    time_limit_seconds: int = 30
    memory_limit_mb: int = 256
    hints: list[str] = field(default_factory=list)
    solution_outline: str = ""
    evaluation_rubric: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "language": self.language,
            "difficulty": self.difficulty,
            "description": self.description,
            "problem_statement": self.problem_statement,
            "constraints": self.constraints,
            "examples": self.examples,
            "starter_code": self.starter_code,
            "test_cases": self.test_cases,
            "time_limit_seconds": self.time_limit_seconds,
            "memory_limit_mb": self.memory_limit_mb,
            "hints": self.hints,
            "solution_outline": self.solution_outline,
            "evaluation_rubric": self.evaluation_rubric,
        }


@dataclass
class CodeIssue:
    """A detected issue in candidate code."""

    severity: str  # ERROR | WARNING | INFO
    issue_type: str  # performance | security | style | correctness
    line: int | None = None
    description: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "type": self.issue_type,
            "line": self.line,
            "description": self.description,
            "suggestion": self.suggestion,
        }


@dataclass
class CodingEvaluation:
    """Complete evaluation of a candidate's coding submission."""

    # Scores (0.0 - 1.0)
    correctness_score: float = 0.0
    time_complexity_score: float = 0.0
    space_complexity_score: float = 0.0
    code_quality_score: float = 0.0
    security_score: float = 0.0
    naming_score: float = 0.0
    best_practices_score: float = 0.0
    overall_score: float = 0.0

    # Analysis
    time_complexity: str = "Unknown"
    space_complexity: str = "Unknown"
    issues: list[CodeIssue] = field(default_factory=list)
    security_issues: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    overall_feedback: str = ""
    pass_fail: str = "FAIL"  # PASS | FAIL | PARTIAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "correctness_score": round(self.correctness_score, 4),
            "time_complexity_score": round(self.time_complexity_score, 4),
            "space_complexity_score": round(self.space_complexity_score, 4),
            "code_quality_score": round(self.code_quality_score, 4),
            "security_score": round(self.security_score, 4),
            "naming_score": round(self.naming_score, 4),
            "best_practices_score": round(self.best_practices_score, 4),
            "overall_score": round(self.overall_score, 4),
            "time_complexity": self.time_complexity,
            "space_complexity": self.space_complexity,
            "issues": [i.to_dict() for i in self.issues],
            "security_issues": self.security_issues,
            "strengths": self.strengths,
            "improvements": self.improvements,
            "overall_feedback": self.overall_feedback,
            "pass_fail": self.pass_fail,
        }


class CodingAssessmentAgent:
    """AI agent for generating and evaluating coding assessments."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or get_llm_client()

    # ------------------------------------------------------------------
    # Challenge Generation
    # ------------------------------------------------------------------

    async def generate_challenge(
        self,
        language: str,
        difficulty: str = "INTERMEDIATE",
        topic: str = "Data Structures",
        role_context: str = "Software Engineer",
        model: str | None = None,
    ) -> CodingChallenge:
        """Generate a coding challenge tailored to the candidate profile.

        Args:
            language: Target programming language.
            difficulty: BEGINNER | INTERMEDIATE | ADVANCED | EXPERT
            topic: Algorithmic topic (e.g., 'Dynamic Programming', 'REST API').
            role_context: Role description for contextual relevance.
        """
        language = language.lower()
        if language not in SUPPORTED_LANGUAGES:
            language = "python"

        difficulty = difficulty.upper()
        if difficulty not in DIFFICULTY_TO_NUM:
            difficulty = "INTERMEDIATE"

        response = await self._llm.complete(
            prompt=PromptLibrary.coding_challenge_user(language, difficulty, topic, role_context),
            system=PromptLibrary.CODING_SYSTEM,
            model=model,
            json_mode=True,
            temperature=0.5,  # More creative for challenge variety
            num_predict=3000,
        )

        data = ResponseParser.extract_json_object(response) if response else {}

        if not data:
            logger.warning("LLM failed to generate coding challenge — using fallback")
            return self._fallback_challenge(language, difficulty, topic)

        return CodingChallenge(
            title=ResponseParser.get_str(data, "title", f"{topic} Challenge"),
            language=language,
            difficulty=difficulty,
            description=ResponseParser.get_str(data, "description"),
            problem_statement=ResponseParser.get_str(data, "problem_statement"),
            constraints=ResponseParser.get_list(data, "constraints"),
            examples=ResponseParser.get_list(data, "examples"),
            starter_code=ResponseParser.get_str(data, "starter_code"),
            test_cases=ResponseParser.get_list(data, "test_cases"),
            time_limit_seconds=int(data.get("time_limit_seconds", 30)),
            memory_limit_mb=int(data.get("memory_limit_mb", 256)),
            hints=ResponseParser.get_list(data, "hints"),
            solution_outline=ResponseParser.get_str(data, "solution_outline"),
            evaluation_rubric=ResponseParser.get_dict(data, "evaluation_rubric"),
        )

    async def generate_challenge_set(
        self,
        language: str,
        difficulty: str = "INTERMEDIATE",
        topics: list[str] | None = None,
        role_context: str = "Software Engineer",
        count: int = 3,
        model: str | None = None,
    ) -> list[CodingChallenge]:
        """Generate multiple challenges across different topics."""
        if not topics:
            topics = ["Data Structures", "Algorithms", "System Design"]

        topics = topics[:count]

        tasks = [
            self.generate_challenge(language, difficulty, topic, role_context, model)
            for topic in topics
        ]
        return await asyncio.gather(*tasks)

    # ------------------------------------------------------------------
    # Code Evaluation
    # ------------------------------------------------------------------

    async def evaluate_submission(
        self,
        challenge: CodingChallenge,
        candidate_code: str,
        language: str | None = None,
        test_results: str = "",
        model: str | None = None,
    ) -> CodingEvaluation:
        """Evaluate a candidate's code submission.

        Args:
            challenge: The original challenge specification.
            candidate_code: The candidate's submitted code.
            language: Programming language (defaults to challenge.language).
            test_results: Optional external test execution results.
            model: Optional Ollama model override.
        """
        lang = language or challenge.language
        safe_code = ResponseParser.sanitize_user_input(candidate_code, max_length=3000)
        challenge_desc = challenge.problem_statement or challenge.description

        response = await self._llm.complete(
            prompt=PromptLibrary.coding_evaluation_user(
                challenge_desc, safe_code, lang, test_results or "Tests not run"
            ),
            system=PromptLibrary.CODING_SYSTEM,
            model=model,
            json_mode=True,
            temperature=0.1,
            num_predict=2000,
        )

        data = ResponseParser.extract_json_object(response) if response else {}

        if not data:
            logger.warning("LLM code evaluation returned empty response")
            return CodingEvaluation(overall_feedback="Evaluation unavailable. Manual review needed.")

        eval_score_fields = [
            "correctness_score", "time_complexity_score", "space_complexity_score",
            "code_quality_score", "security_score", "naming_score",
            "best_practices_score", "overall_score",
        ]
        data = ResponseParser.ensure_score_fields(data, eval_score_fields, default=0.5)

        # Parse issues
        raw_issues = data.get("issues", [])
        issues: list[CodeIssue] = []
        for issue in raw_issues:
            if isinstance(issue, dict):
                issues.append(CodeIssue(
                    severity=str(issue.get("severity", "WARNING")).upper(),
                    issue_type=str(issue.get("type", "style")),
                    line=issue.get("line"),
                    description=str(issue.get("description", "")),
                    suggestion=str(issue.get("suggestion", "")),
                ))

        # Sort issues by severity
        issues.sort(key=lambda i: SEVERITY_ORDER.get(i.severity, 0), reverse=True)

        pass_fail = ResponseParser.normalize_decision(
            data.get("pass_fail", "FAIL"),
            valid={"PASS", "FAIL", "PARTIAL"},
            default="FAIL",
        )

        return CodingEvaluation(
            correctness_score=data["correctness_score"],
            time_complexity_score=data["time_complexity_score"],
            space_complexity_score=data["space_complexity_score"],
            code_quality_score=data["code_quality_score"],
            security_score=data["security_score"],
            naming_score=data["naming_score"],
            best_practices_score=data["best_practices_score"],
            overall_score=data["overall_score"],
            time_complexity=ResponseParser.get_str(data, "time_complexity", "O(n)"),
            space_complexity=ResponseParser.get_str(data, "space_complexity", "O(n)"),
            issues=issues,
            security_issues=ResponseParser.get_list(data, "security_issues"),
            strengths=ResponseParser.get_list(data, "strengths"),
            improvements=ResponseParser.get_list(data, "improvements"),
            overall_feedback=ResponseParser.get_str(data, "overall_feedback"),
            pass_fail=pass_fail,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_challenge(language: str, difficulty: str, topic: str) -> CodingChallenge:
        """Return a basic fallback challenge when LLM fails."""
        return CodingChallenge(
            title=f"{topic} Challenge ({difficulty})",
            language=language,
            difficulty=difficulty,
            description=f"Implement a {difficulty.lower()} {topic.lower()} solution in {language}.",
            problem_statement=f"Write a {language} function to solve a {topic} problem.",
            starter_code=f"# {language.capitalize()} solution\ndef solution():\n    pass",
            constraints=["Time limit: 30 seconds", "Memory: 256 MB"],
            evaluation_rubric={
                "correctness": 40,
                "time_complexity": 20,
                "space_complexity": 15,
                "code_quality": 15,
                "security": 10,
            },
        )
