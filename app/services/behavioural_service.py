"""AI Behavioural Interview service.

Orchestrates custom behavioral templates setups and candidate answer audits.
"""

from __future__ import annotations

import logging
import json
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.behavioural_interview import (
    BehaviouralInterviewSession,
    BehaviouralInterviewQuestion,
)

logger = logging.getLogger(__name__)


class BehaviouralInterviewService:
    """Enterprise AI Behavioural Interview Service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def create_interview_session(
        self,
        company_id: uuid.UUID,
        role: str,
        experience_years: int,
        seniority: str,
        company_culture: str,
        model: Optional[str] = None,
    ) -> BehaviouralInterviewSession:
        """Create a custom behavioural interview session and populate targeted questions."""
        session = BehaviouralInterviewSession(
            id=uuid.uuid4(),
            company_id=company_id,
            role=role,
            experience_years=experience_years,
            seniority=seniority,
            company_culture=company_culture,
        )
        self.db.add(session)
        await self.db.flush()

        try:
            prompt = PromptLibrary.ai_behavioural_generator_user(
                role=role,
                experience_years=experience_years,
                seniority=seniority,
                company_culture=company_culture
            )
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_BEHAVIOURAL_INTERVIEW_GEN,
                model=model,
                json_mode=True,
                temperature=0.4
            )
            data = ResponseParser.extract_json_object(res_text)
            questions_list = data.get("questions", [])
        except Exception as exc:
            logger.error("AI Behavioural interview setup failed: %s", exc)
            questions_list = [
                {
                    "dimension": "STAR_METHOD",
                    "question_text": "Tell me about a challenging situation you solved at work. Use Situation, Task, Action, Result format."
                }
            ]

        for q in questions_list:
            question = BehaviouralInterviewQuestion(
                id=uuid.uuid4(),
                session_id=session.id,
                dimension=q.get("dimension", "STAR_METHOD").upper(),
                question_text=q.get("question_text", "Describe your process."),
            )
            self.db.add(question)

        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Behavioural session created: %s with %d questions", session.id, len(questions_list))
        return session

    async def evaluate_question_response(
        self,
        question_id: uuid.UUID,
        candidate_response: str,
        model: Optional[str] = None,
    ) -> BehaviouralInterviewQuestion:
        """Submit answer and run LLM evaluation audit on STAR structures."""
        stmt = select(BehaviouralInterviewQuestion).where(BehaviouralInterviewQuestion.id == question_id)
        res = await self.db.execute(stmt)
        question = res.scalar_one_or_none()
        if not question:
            raise ValueError("Question not found.")

        try:
            prompt = PromptLibrary.ai_behavioural_evaluator_user(
                question_text=question.question_text,
                candidate_response=candidate_response
            )
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_BEHAVIOURAL_INTERVIEW_EVAL,
                model=model,
                json_mode=True,
                temperature=0.2
            )
            eval_data = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("AI Behavioural response evaluation failed: %s", exc)
            eval_data = {
                "evaluation_score": 5,
                "evaluation_feedback": "Auto-compiled standard feedback due to LLM error."
            }

        question.candidate_response = candidate_response
        question.evaluation_score = int(eval_data.get("evaluation_score", 5))
        question.evaluation_feedback = eval_data.get("evaluation_feedback", "Completed.")

        await self.db.commit()
        await self.db.refresh(question)
        logger.info("Response evaluated for question %s, score: %d", question_id, question.evaluation_score)
        return question
