"""Poll the durable work queue. Row locks serialize delivery and retries."""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from app.db.base import tenant_id_ctx
from app.db.database import AsyncSessionLocal, engine
from app.models.automation_jobs import AutomationExecution
from app.workers.celery_app import celery_app


async def drain_jobs(limit=50):
    from app.services.notification_automation import schedule_due, execute_notification
    from app.services.autopilot_workflows import execute_onboarding_retry
    context = tenant_id_ctx.set(None)
    completed = 0
    try:
        async with AsyncSessionLocal() as db, db.begin():
            await schedule_due(db)
        for _ in range(limit):
            async with AsyncSessionLocal() as db, db.begin():
                job = await db.scalar(select(AutomationExecution).where(
                    AutomationExecution.status == "pending", AutomationExecution.available_at <= datetime.now(timezone.utc)
                ).order_by(AutomationExecution.available_at).with_for_update(skip_locked=True).limit(1))
                if not job:
                    break
                scope = tenant_id_ctx.set(job.company_id)
                try:
                    job.attempts += 1
                    job.started_at = datetime.now(timezone.utc)
                    job.status = "running"
                    # Savepoint rolls back partial domain work but preserves the failure record.
                    async with db.begin_nested():
                        if job.kind == "notification":
                            result = await execute_notification(db, job)
                        elif job.kind == "onboarding":
                            result = await execute_onboarding_retry(db, job)
                        else:
                            raise ValueError("Unsupported automation job kind")
                    job.result, job.status, job.error = result, "completed", None
                    job.completed_at = datetime.now(timezone.utc)
                    completed += 1
                except Exception as exc:
                    job.status = "failed"
                    job.error = f"{type(exc).__name__}: execution failed; consult the protected worker log"
                finally:
                    tenant_id_ctx.reset(scope)
        return {"completed": completed}
    finally:
        tenant_id_ctx.reset(context)


if celery_app is not None:
    @celery_app.task(name="app.workers.automation_tasks.drain", acks_late=True)
    def drain_automation_jobs():
        async def run():
            try:
                return await drain_jobs()
            finally:
                await engine.dispose()
        return asyncio.run(run())
