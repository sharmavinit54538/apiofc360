"""Recurring pulse surveys, k-anonymous analytics, and recognition rewards."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.employee import Employee
from app.models.engagement import (
    EngagementAnswer, EngagementQuestion, EngagementResponse, EngagementSurvey,
    ManagerActionPlan, PeerRecognition, RewardLedgerEntry,
)


def _now() -> datetime:
    return datetime.now(UTC)


class EngagementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee:
        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id,
            Employee.is_deleted.is_(False), Employee.status == "ACTIVE",
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Active employee not found in this tenant.")
        return employee

    async def _survey(self, survey_id: uuid.UUID, company_id: uuid.UUID) -> EngagementSurvey:
        survey = (await self.session.execute(select(EngagementSurvey).options(
            selectinload(EngagementSurvey.questions),
        ).where(EngagementSurvey.id == survey_id, EngagementSurvey.company_id == company_id))).scalar_one_or_none()
        if survey is None:
            raise LookupError("Engagement survey not found.")
        return survey

    async def create_survey(
        self, *, company_id: uuid.UUID, title: str, starts_at: datetime, ends_at: datetime,
        questions: list[dict], frequency: str = "ONCE", anonymous: bool = True,
        min_group_size: int = 5,
    ) -> EngagementSurvey:
        frequency = frequency.upper()
        if frequency not in {"ONCE", "WEEKLY", "MONTHLY", "QUARTERLY"}:
            raise ValueError("Unsupported survey frequency.")
        if ends_at <= starts_at:
            raise ValueError("Survey end must be after its start.")
        if min_group_size < 2:
            raise ValueError("Anonymous feedback requires k-anonymity of at least two.")
        if not questions:
            raise ValueError("A pulse survey requires at least one question.")
        survey = EngagementSurvey(
            id=uuid.uuid4(), company_id=company_id, title=title.strip(), frequency=frequency,
            starts_at=starts_at, ends_at=ends_at,
            next_run_at=ends_at if frequency != "ONCE" else None,
            is_anonymous=anonymous, min_group_size=min_group_size, status="ACTIVE",
        )
        self.session.add(survey)
        await self.session.flush()
        for index, item in enumerate(questions, start=1):
            question_type = str(item.get("question_type") or item.get("type") or "").upper()
            if question_type not in {"ENPS", "RATING", "TEXT"}:
                raise ValueError("Survey question type must be ENPS, RATING, or TEXT.")
            self.session.add(EngagementQuestion(
                id=uuid.uuid4(), company_id=company_id, survey_id=survey.id,
                question_text=str(item["question_text"]).strip(), question_type=question_type,
                sequence_number=int(item.get("sequence_number", index)),
                is_required=bool(item.get("is_required", True)),
            ))
        await self.session.commit()
        return await self._survey(survey.id, company_id)

    def _respondent_hash(self, survey_id: uuid.UUID, employee_id: uuid.UUID) -> str:
        secret = settings.SECRET_KEY.get_secret_value().encode()
        return hmac.new(secret, f"survey-respondent:{survey_id}:{employee_id}".encode(), hashlib.sha256).hexdigest()

    async def submit_response(
        self, survey_id: uuid.UUID, *, company_id: uuid.UUID,
        employee_id: uuid.UUID, answers: dict[uuid.UUID, dict],
        submitted_at: datetime | None = None,
    ) -> EngagementResponse:
        survey = await self._survey(survey_id, company_id)
        employee = await self._employee(employee_id, company_id)
        submitted_at = submitted_at or _now()
        if survey.status != "ACTIVE" or not (survey.starts_at <= submitted_at <= survey.ends_at):
            raise ValueError("Survey is not accepting responses.")
        respondent_hash = self._respondent_hash(survey_id, employee_id)
        existing = (await self.session.execute(select(EngagementResponse).where(
            EngagementResponse.survey_id == survey_id,
            EngagementResponse.respondent_key_hash == respondent_hash,
        ))).scalar_one_or_none()
        if existing:
            raise ValueError("This employee has already responded to the survey.")
        by_id = {question.id: question for question in survey.questions}
        for question in survey.questions:
            value = answers.get(question.id)
            if question.is_required and not value:
                raise ValueError(f"Answer required for question {question.sequence_number}.")
            if not value:
                continue
            numeric, text = value.get("numeric_value"), value.get("text_value")
            if question.question_type == "ENPS" and (numeric is None or not 0 <= float(numeric) <= 10):
                raise ValueError("eNPS answers must be between 0 and 10.")
            if question.question_type == "RATING" and (numeric is None or not 1 <= float(numeric) <= 5):
                raise ValueError("Rating answers must be between 1 and 5.")
            if question.question_type == "TEXT" and not str(text or "").strip():
                raise ValueError("Text answers cannot be empty.")
        response = EngagementResponse(
            id=uuid.uuid4(), company_id=company_id, survey_id=survey_id,
            employee_id=None if survey.is_anonymous else employee_id,
            respondent_key_hash=respondent_hash,
            department=employee.department, submitted_at=submitted_at,
        )
        self.session.add(response)
        await self.session.flush()
        for question_id, value in answers.items():
            if question_id not in by_id:
                raise ValueError("Answer references a question outside this survey.")
            self.session.add(EngagementAnswer(
                id=uuid.uuid4(), company_id=company_id, response_id=response.id, question_id=question_id,
                numeric_value=Decimal(str(value["numeric_value"])) if value.get("numeric_value") is not None else None,
                text_value=value.get("text_value"),
            ))
        await self.session.commit()
        return response

    async def survey_results(self, survey_id: uuid.UUID, *, company_id: uuid.UUID) -> dict:
        survey = await self._survey(survey_id, company_id)
        responses = (await self.session.execute(select(EngagementResponse).options(
            selectinload(EngagementResponse.answers),
        ).where(
            EngagementResponse.company_id == company_id, EngagementResponse.survey_id == survey_id,
        ))).scalars().all()
        questions = (await self.session.execute(select(EngagementQuestion).where(
            EngagementQuestion.company_id == company_id, EngagementQuestion.survey_id == survey_id,
        ))).scalars().all()
        question_types = {question.id: question.question_type for question in questions}

        def aggregate(rows: list[EngagementResponse]) -> dict:
            suppressed = survey.is_anonymous and len(rows) < survey.min_group_size
            if suppressed:
                return {"response_count": len(rows), "suppressed": True, "enps": None, "average_rating": None, "comments": []}
            enps_scores, ratings, comments = [], [], []
            for response in rows:
                for answer in response.answers:
                    question_type = question_types.get(answer.question_id)
                    if question_type == "ENPS" and answer.numeric_value is not None:
                        enps_scores.append(float(answer.numeric_value))
                    elif question_type == "RATING" and answer.numeric_value is not None:
                        ratings.append(float(answer.numeric_value))
                    elif question_type == "TEXT" and answer.text_value:
                        comments.append(answer.text_value)
            enps = None
            if enps_scores:
                promoters = sum(score >= 9 for score in enps_scores)
                detractors = sum(score <= 6 for score in enps_scores)
                enps = round((promoters - detractors) * 100 / len(enps_scores), 2)
            return {
                "response_count": len(rows), "suppressed": False, "enps": enps,
                "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "comments": comments,
            }

        departments = {}
        for department in sorted({row.department or "UNSPECIFIED" for row in responses}):
            departments[department] = aggregate([row for row in responses if (row.department or "UNSPECIFIED") == department])
        return {"survey_id": str(survey_id), "k_anonymity": survey.min_group_size if survey.is_anonymous else None,
                "overall": aggregate(responses), "departments": departments}

    async def process_recurring(self, *, company_id: uuid.UUID, now: datetime | None = None) -> list[EngagementSurvey]:
        now = now or _now()
        surveys = (await self.session.execute(select(EngagementSurvey).options(
            selectinload(EngagementSurvey.questions),
        ).where(
            EngagementSurvey.company_id == company_id, EngagementSurvey.status == "ACTIVE",
            EngagementSurvey.frequency != "ONCE", EngagementSurvey.next_run_at.isnot(None),
            EngagementSurvey.next_run_at <= now,
        ))).scalars().all()
        created = []
        intervals = {"WEEKLY": timedelta(days=7), "MONTHLY": timedelta(days=30), "QUARTERLY": timedelta(days=90)}
        for survey in surveys:
            start = survey.ends_at
            end = start + intervals[survey.frequency]
            clone = EngagementSurvey(
                id=uuid.uuid4(), company_id=company_id, title=survey.title, frequency=survey.frequency,
                starts_at=start, ends_at=end, next_run_at=end,
                recurrence_parent_id=survey.recurrence_parent_id or survey.id,
                is_anonymous=survey.is_anonymous, min_group_size=survey.min_group_size, status="ACTIVE",
            )
            survey.status = "COMPLETED"
            survey.next_run_at = None
            self.session.add(clone)
            await self.session.flush()
            for question in survey.questions:
                self.session.add(EngagementQuestion(
                    id=uuid.uuid4(), company_id=company_id, survey_id=clone.id,
                    question_text=question.question_text, question_type=question.question_type,
                    sequence_number=question.sequence_number, is_required=question.is_required,
                ))
            created.append(clone)
        await self.session.commit()
        return created

    async def create_action_plan(
        self, *, company_id: uuid.UUID, manager_employee_id: uuid.UUID,
        title: str, actions: list[dict], due_date: date, survey_id: uuid.UUID | None = None,
    ) -> ManagerActionPlan:
        await self._employee(manager_employee_id, company_id)
        if survey_id:
            await self._survey(survey_id, company_id)
        if not actions:
            raise ValueError("Manager action plan requires at least one action.")
        plan = ManagerActionPlan(
            id=uuid.uuid4(), company_id=company_id, survey_id=survey_id,
            manager_employee_id=manager_employee_id, title=title.strip(), actions_json=actions, due_date=due_date,
        )
        self.session.add(plan)
        await self.session.commit()
        return plan

    async def recognize_peer(
        self, *, company_id: uuid.UUID, sender_employee_id: uuid.UUID,
        recipient_employee_id: uuid.UUID, message: str, points: int,
    ) -> PeerRecognition:
        if sender_employee_id == recipient_employee_id:
            raise ValueError("Peer recognition must be for another employee.")
        await self._employee(sender_employee_id, company_id)
        await self._employee(recipient_employee_id, company_id)
        if not 1 <= points <= 1000 or len(message.strip()) < 5:
            raise ValueError("Recognition requires 1–1000 points and a meaningful message.")
        recognition = PeerRecognition(
            id=uuid.uuid4(), company_id=company_id, sender_employee_id=sender_employee_id,
            recipient_employee_id=recipient_employee_id, message=message.strip(), points=points,
        )
        self.session.add(recognition)
        self.session.add(RewardLedgerEntry(
            id=uuid.uuid4(), company_id=company_id, employee_id=recipient_employee_id,
            recognition_id=recognition.id, entry_type="EARNED", points=points,
        ))
        await self.session.commit()
        return recognition

    async def reward_balance(self, *, company_id: uuid.UUID, employee_id: uuid.UUID) -> int:
        await self._employee(employee_id, company_id)
        rows = (await self.session.execute(select(RewardLedgerEntry).where(
            RewardLedgerEntry.company_id == company_id, RewardLedgerEntry.employee_id == employee_id,
        ))).scalars().all()
        return sum(-row.points if row.entry_type == "REDEEMED" else row.points for row in rows)

    async def redeem_rewards(
        self, *, company_id: uuid.UUID, employee_id: uuid.UUID, points: int, reference: str,
    ) -> RewardLedgerEntry:
        balance = await self.reward_balance(company_id=company_id, employee_id=employee_id)
        if points < 1 or points > balance:
            raise ValueError("Insufficient reward balance.")
        entry = RewardLedgerEntry(
            id=uuid.uuid4(), company_id=company_id, employee_id=employee_id,
            entry_type="REDEEMED", points=points, reference=reference,
        )
        self.session.add(entry)
        await self.session.commit()
        return entry
