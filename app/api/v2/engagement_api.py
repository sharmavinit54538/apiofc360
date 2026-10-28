"""Pulse survey, eNPS, action plan, recognition, and rewards APIs."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v2.enterprise_dependencies import (
    Claims, Session, company_id, ok, require_admin, require_manager, translate, user_id,
)
from app.models.employee import Employee
from app.services.engagement_service import EngagementService

router = APIRouter(prefix="/engagement", tags=["Engagement v2"])


class SurveyRequest(BaseModel):
    title: str
    starts_at: datetime
    ends_at: datetime
    questions: list[dict]
    frequency: str = "ONCE"
    anonymous: bool = True
    min_group_size: int = Field(5, ge=2)


class ResponseRequest(BaseModel):
    answers: dict[uuid.UUID, dict]
    submitted_at: datetime | None = None


class ActionPlanRequest(BaseModel):
    manager_employee_id: uuid.UUID
    title: str
    actions: list[dict]
    due_date: date
    survey_id: uuid.UUID | None = None


class RecognitionRequest(BaseModel):
    recipient_employee_id: uuid.UUID
    message: str = Field(min_length=5)
    points: int = Field(ge=1, le=1000)


class RedeemRequest(BaseModel):
    points: int = Field(ge=1)
    reference: str


async def _current_employee(db, claims) -> Employee:
    employee = (await db.execute(select(Employee).where(
        Employee.user_id == user_id(claims), Employee.company_id == company_id(claims),
        Employee.is_deleted.is_(False),
    ))).scalar_one_or_none()
    if employee is None:
        raise LookupError("Employee profile not found for current user.")
    return employee


@router.post("/surveys", status_code=201)
async def create_survey(body: SurveyRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        survey = await EngagementService(db).create_survey(company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(survey.id), "status": survey.status, "question_ids": [str(q.id) for q in survey.questions]})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/surveys/{survey_id}/responses", status_code=201)
async def submit_survey_response(survey_id: uuid.UUID, body: ResponseRequest, claims: Claims, db: Session):
    try:
        employee = await _current_employee(db, claims)
        response = await EngagementService(db).submit_response(
            survey_id, company_id=company_id(claims), employee_id=employee.id, **body.model_dump(),
        )
        return ok({"id": str(response.id), "submitted_at": response.submitted_at.isoformat(), "anonymous": response.employee_id is None})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.get("/surveys/{survey_id}/results")
async def survey_results(survey_id: uuid.UUID, claims: Claims, db: Session):
    require_manager(claims)
    try:
        return ok(await EngagementService(db).survey_results(survey_id, company_id=company_id(claims)))
    except LookupError as exc:
        translate(exc)


@router.post("/surveys/recurring/process")
async def process_recurring_surveys(claims: Claims, db: Session):
    require_admin(claims)
    rows = await EngagementService(db).process_recurring(company_id=company_id(claims))
    return ok({"created_count": len(rows), "survey_ids": [str(row.id) for row in rows]})


@router.post("/action-plans", status_code=201)
async def create_action_plan(body: ActionPlanRequest, claims: Claims, db: Session):
    require_manager(claims)
    try:
        plan = await EngagementService(db).create_action_plan(company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(plan.id), "status": plan.status})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.post("/recognitions", status_code=201)
async def recognize_peer(body: RecognitionRequest, claims: Claims, db: Session):
    try:
        employee = await _current_employee(db, claims)
        recognition = await EngagementService(db).recognize_peer(
            company_id=company_id(claims), sender_employee_id=employee.id, **body.model_dump(),
        )
        return ok({"id": str(recognition.id), "points": recognition.points})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.get("/rewards/balance")
async def reward_balance(claims: Claims, db: Session):
    try:
        employee = await _current_employee(db, claims)
        balance = await EngagementService(db).reward_balance(company_id=company_id(claims), employee_id=employee.id)
        return ok({"employee_id": str(employee.id), "balance_points": balance})
    except LookupError as exc:
        translate(exc)


@router.post("/rewards/redeem")
async def redeem_rewards(body: RedeemRequest, claims: Claims, db: Session):
    try:
        employee = await _current_employee(db, claims)
        entry = await EngagementService(db).redeem_rewards(
            company_id=company_id(claims), employee_id=employee.id, **body.model_dump(),
        )
        return ok({"id": str(entry.id), "redeemed_points": entry.points})
    except (ValueError, LookupError) as exc:
        translate(exc)
