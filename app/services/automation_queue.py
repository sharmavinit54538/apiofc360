"""Transactional queue: an acknowledged job is durable, never fictitious."""
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.automation_jobs import AutomationExecution


async def enqueue(db, *, company_id, actor_id, kind, key, payload, rule_id=None, delay=0):
    job_id = uuid.uuid4()
    await db.execute(insert(AutomationExecution).values(
        id=job_id, company_id=company_id, actor_id=actor_id, kind=kind,
        idempotency_key=key, payload=payload, rule_id=rule_id, status="pending", attempts=0,
        available_at=datetime.now(timezone.utc) + timedelta(minutes=delay),
    ).on_conflict_do_nothing(constraint="uq_automation_execution_key"))
    return await db.scalar(select(AutomationExecution).where(
        AutomationExecution.company_id == company_id, AutomationExecution.kind == kind,
        AutomationExecution.idempotency_key == key))


def serialize(job):
    return {"id": str(job.id), "kind": job.kind, "status": job.status,
            "rule_id": str(job.rule_id) if job.rule_id else None, "attempts": job.attempts,
            "details": job.error, "result": job.result, "created_at": job.created_at,
            "started_at": job.started_at, "completed_at": job.completed_at}


async def retry(db, company_id, job_id):
    job = await db.scalar(select(AutomationExecution).where(
        AutomationExecution.id == job_id, AutomationExecution.company_id == company_id).with_for_update())
    if not job:
        raise HTTPException(404, "Automation activity not found")
    if job.status != "failed":
        raise HTTPException(409, "Only failed work can be retried")
    job.status, job.error = "pending", None
    job.available_at = datetime.now(timezone.utc)
    await db.commit()
    return serialize(job)
