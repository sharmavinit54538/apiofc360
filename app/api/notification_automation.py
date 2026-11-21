"""Notification automation API backed by tenant-owned rules and execution records."""
import uuid
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from app.api.v2.enterprise_dependencies import Claims, Session, company_id, user_id, require_admin, ok
from app.models.automation_jobs import NotificationAutomationRule as Rule, AutomationExecution as Job
from app.services.automation_queue import enqueue, retry, serialize

router = APIRouter()


class RulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    trigger_event: str = Field(min_length=1, max_length=100)
    channels: list[Literal["IN_APP"]] = Field(default_factory=lambda: ["IN_APP"], min_length=1)
    recipients: list[str] = Field(default_factory=lambda: ["ALL_EMPLOYEES"], min_length=1, max_length=1000)
    template: str = Field(min_length=1, max_length=1000)
    is_enabled: bool = True
    delay_minutes: int = Field(0, ge=0, le=10080)
    retry_count: int = Field(3, ge=0, le=10)
    next_run_at: datetime | None = None
    interval_minutes: int | None = Field(None, ge=1, le=525600)


def rule_data(rule):
    return {**rule.configuration, "id": str(rule.id), "name": rule.name,
            "trigger_event": rule.trigger_event, "is_enabled": rule.is_enabled,
            "next_run_at": rule.next_run_at, "interval_minutes": rule.interval_minutes,
            "last_triggered": rule.last_triggered, "status": "ACTIVE" if rule.is_enabled else "PAUSED"}


async def owned_rule(db, cid, rid):
    rule = await db.scalar(select(Rule).where(Rule.id == rid, Rule.company_id == cid).with_for_update())
    if not rule:
        raise HTTPException(404, "Automation rule not found")
    return rule


@router.get("/automation-rules")
@router.head("/automation-rules")
async def rules(claims: Claims, db: Session, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), enabled: bool | None = None):
    require_admin(claims)
    stmt = select(Rule).where(Rule.company_id == company_id(claims))
    if enabled is not None:
        stmt = stmt.where(Rule.is_enabled == enabled)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.scalars(stmt.order_by(Rule.created_at.desc()).offset((page-1)*limit).limit(limit))).all()
    return ok({"items": [rule_data(r) for r in rows], "total": total, "page": page, "limit": limit})


@router.post("/automation-rules", status_code=201)
async def create(payload: RulePayload, claims: Claims, db: Session):
    require_admin(claims)
    rule = Rule(company_id=company_id(claims), created_by=user_id(claims))
    apply_payload(rule, payload)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return ok(rule_data(rule))


def apply_payload(rule, payload):
    if payload.next_run_at and payload.next_run_at.tzinfo is None:
        raise HTTPException(422, "Scheduled time must include a timezone")
    for recipient in payload.recipients:
        if recipient != "ALL_EMPLOYEES":
            try:
                uuid.UUID(recipient)
            except ValueError as exc:
                raise HTTPException(422, "Recipients must be user UUIDs or ALL_EMPLOYEES") from exc
    rule.name, rule.trigger_event, rule.is_enabled = payload.name, payload.trigger_event, payload.is_enabled
    rule.next_run_at, rule.interval_minutes = payload.next_run_at, payload.interval_minutes
    rule.configuration = payload.model_dump(mode="json", exclude={"next_run_at"})


@router.put("/automation-rules/{rule_id}")
async def update(rule_id: uuid.UUID, payload: RulePayload, claims: Claims, db: Session):
    require_admin(claims)
    rule = await owned_rule(db, company_id(claims), rule_id)
    apply_payload(rule, payload)
    await db.commit()
    return ok(rule_data(rule))


@router.post("/automation-rules/{rule_id}/toggle")
@router.post("/scheduled-jobs/{rule_id}/toggle")
async def toggle(rule_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    rule = await owned_rule(db, company_id(claims), rule_id)
    rule.is_enabled = not rule.is_enabled
    await db.commit()
    return ok(rule_data(rule))


@router.post("/automation-rules/{rule_id}/test", status_code=202)
async def test_rule(rule_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    cid, uid = company_id(claims), user_id(claims)
    await owned_rule(db, cid, rule_id)
    job = await enqueue(db, company_id=cid, actor_id=uid, kind="notification", key=str(uuid.uuid4()),
                        rule_id=rule_id, payload={"recipient_ids": [str(uid)], "test": True})
    await db.commit()
    return ok(serialize(job), "Test notification persisted for worker execution")


@router.get("/activity")
async def activity(claims: Claims, db: Session, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), status: str | None = None):
    require_admin(claims)
    stmt = select(Job).where(Job.company_id == company_id(claims), Job.kind == "notification")
    if status:
        stmt = stmt.where(Job.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.scalars(stmt.order_by(Job.created_at.desc()).offset((page-1)*limit).limit(limit))).all()
    return ok({"items": [serialize(r) for r in rows], "total": total, "page": page, "limit": limit})


@router.post("/activity/{act_id}/retry", status_code=202)
async def retry_activity(act_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    return ok(await retry(db, company_id(claims), act_id), "Retry persisted for worker execution")


@router.get("/scheduled-jobs")
async def schedules(claims: Claims, db: Session, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    require_admin(claims)
    stmt = select(Rule).where(Rule.company_id == company_id(claims), Rule.next_run_at.is_not(None))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await db.scalars(stmt.order_by(Rule.next_run_at).offset((page-1)*limit).limit(limit))).all()
    return ok({"items": [rule_data(r) for r in rows], "total": total, "page": page, "limit": limit})
