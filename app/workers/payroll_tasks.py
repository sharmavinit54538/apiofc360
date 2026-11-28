"""Celery background tasks and asynchronous job tracking for Payroll module.

Handles:
- Payroll Run processing engine
- Payslip PDF generation in batch
- Payment batch bank file generation (HDFC, ICICI, SBI, Generic NEFT)
- Payroll Reports CSV/XLSX export
- Statutory compliance reports generation (PF ECR, ESI, PT, TDS)
- Bulk Compensation / Variable Inputs apply
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from app.core.config import settings
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# Fallback in-memory job store & tracked background tasks for local async fallback
_IN_MEMORY_JOBS: dict[str, dict[str, Any]] = {}
_ACTIVE_ASYNC_TASKS: set[asyncio.Task[Any]] = set()

_TRANSIENT_TASK_EXCEPTIONS = (TimeoutError, ConnectionError, OSError)


def _schedule_fallback_task(coro: Any, *, name: str) -> asyncio.Task[Any]:
    """Create and track an in-process asyncio background task for clean shutdown."""
    task = asyncio.create_task(coro, name=name)
    _ACTIVE_ASYNC_TASKS.add(task)

    def _on_done(done_task: asyncio.Task[Any]) -> None:
        _ACTIVE_ASYNC_TASKS.discard(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc is not None:
            logger.error("Fallback background task %s failed: %s", name, exc)

    task.add_done_callback(_on_done)
    return task


async def shutdown_background_tasks(timeout: float = 5.0) -> None:
    """Drain or cancel pending in-process payroll fallback tasks on app shutdown."""
    pending = [t for t in list(_ACTIVE_ASYNC_TASKS) if not t.done()]
    if not pending:
        return
    logger.info("Draining %d pending in-process payroll background task(s)...", len(pending))
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)
    for task in done:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()


def _is_permanent_task_error(exc: Exception) -> bool:
    """Distinguish permanent validation/domain errors (4xx/ValueError) from retryable transient errors."""
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return True
    try:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException) and 400 <= int(exc.status_code) < 500:
            return True
    except Exception:
        pass
    return False


def _is_transient_task_error(exc: Exception) -> bool:
    """Return True for transient network/DB/timeout errors suitable for Celery retry."""
    if isinstance(exc, _TRANSIENT_TASK_EXCEPTIONS):
        return True
    try:
        from sqlalchemy.exc import OperationalError, TimeoutError as SATimeoutError
        if isinstance(exc, (OperationalError, SATimeoutError)):
            return True
    except Exception:
        pass
    try:
        from celery.exceptions import SoftTimeLimitExceeded
        if isinstance(exc, SoftTimeLimitExceeded):
            return False  # Do not silently re-loop a soft timeout unless task logic allows
    except Exception:
        pass
    return False


def _execute_celery_coro(task_self: Any, coro: Any, *, task_label: str) -> Any:
    """Execute an async worker coroutine inside Celery with structured logging and bounded retries."""
    try:
        return asyncio.run(coro)
    except Exception as exc:
        if _is_permanent_task_error(exc) or not _is_transient_task_error(exc):
            logger.error(
                "Celery task %s failed permanently | task_id=%s | error_type=%s | error=%s",
                task_label,
                getattr(getattr(task_self, "request", None), "id", None),
                type(exc).__name__,
                exc,
            )
            raise
        retries = int(getattr(getattr(task_self, "request", None), "retries", 0) or 0)
        max_retries = int(getattr(task_self, "max_retries", 3) or 3)
        if retries >= max_retries:
            logger.error(
                "Celery task %s exhausted %d retries | task_id=%s | error=%s",
                task_label,
                max_retries,
                getattr(getattr(task_self, "request", None), "id", None),
                exc,
            )
            raise
        countdown = min(60, (2 ** retries) * 5)
        logger.warning(
            "Celery task %s hit transient error (%s), retrying in %ds (%d/%d)",
            task_label,
            type(exc).__name__,
            countdown,
            retries + 1,
            max_retries,
        )
        raise task_self.retry(exc=exc, countdown=countdown)


class PayrollJobTracker:
    """Manages job status in Redis and local memory for status polling."""

    PREFIX = "payroll:job:"

    @classmethod
    async def create_job(cls, job_type: str, metadata: dict[str, Any] | None = None) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = time.time()
        job_data = {
            "job_id": job_id,
            "job_type": job_type,
            "status": "PENDING",  # PENDING | PROCESSING | COMPLETED | FAILED
            "progress": 0,
            "total": 0,
            "processed": 0,
            "failed": 0,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {},
        }
        _IN_MEMORY_JOBS[job_id] = job_data
        try:
            if getattr(redis_client, "_client", None) is not None:
                await redis_client.set(f"{cls.PREFIX}{job_id}", json.dumps(job_data), ttl_seconds=86400)
        except Exception as exc:
            logger.debug("PayrollJobTracker Redis write skipped (%s): %s", job_id, exc)
        return job_id

    @classmethod
    async def update_job(
        cls,
        job_id: str,
        status: str,
        progress: int | None = None,
        total: int | None = None,
        processed: int | None = None,
        failed: int | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        job = await cls.get_job(job_id) or {
            "job_id": job_id,
            "status": status,
            "progress": progress or 0,
            "total": total or 0,
            "processed": processed or 0,
            "failed": failed or 0,
            "result": result,
            "error": error,
            "created_at": time.time(),
        }
        job["status"] = status
        if progress is not None:
            job["progress"] = progress
        if total is not None:
            job["total"] = total
        if processed is not None:
            job["processed"] = processed
        if failed is not None:
            job["failed"] = failed
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = error
        job["updated_at"] = time.time()

        _IN_MEMORY_JOBS[job_id] = job
        try:
            if getattr(redis_client, "_client", None) is not None:
                await redis_client.set(f"{cls.PREFIX}{job_id}", json.dumps(job), ttl_seconds=86400)
        except Exception as exc:
            logger.debug("PayrollJobTracker Redis update skipped (%s): %s", job_id, exc)

    @classmethod
    async def get_job(cls, job_id: str) -> Optional[dict[str, Any]]:
        if not job_id:
            return None
        try:
            if getattr(redis_client, "_client", None) is not None:
                val = await redis_client.get(f"{cls.PREFIX}{job_id}")
                if val:
                    return json.loads(val)
        except Exception as exc:
            logger.debug("PayrollJobTracker Redis read skipped (%s): %s", job_id, exc)
        return _IN_MEMORY_JOBS.get(job_id)


# ── Celery Task Definitions ──────────────────────────────────────────────────
try:
    from app.workers.celery_app import celery_app, CELERY_AVAILABLE
    if CELERY_AVAILABLE and celery_app is not None:

        _TASK_OPTS = {
            "bind": True,
            "acks_late": True,
            "reject_on_worker_lost": True,
            "max_retries": 3,
            "soft_time_limit": settings.CELERY_TASK_SOFT_TIME_LIMIT,
            "time_limit": settings.CELERY_TASK_TIME_LIMIT,
        }

        @celery_app.task(name="app.workers.payroll_tasks.process_payroll_run_task", **_TASK_OPTS)
        def process_payroll_run_task(self, run_id_str: str, job_id: str, company_id_str: str | None = None):
            return _execute_celery_coro(
                self,
                _async_process_payroll_run(run_id_str, job_id, company_id_str),
                task_label="process_payroll_run_task",
            )

        @celery_app.task(name="app.workers.payroll_tasks.recover_abandoned_payroll_runs_task", **_TASK_OPTS)
        def recover_abandoned_payroll_runs_task(self):
            return _execute_celery_coro(
                self,
                _async_recover_abandoned_payroll_runs(),
                task_label="recover_abandoned_payroll_runs_task",
            )

        @celery_app.task(name="app.workers.payroll_tasks.generate_payslips_batch_task", **_TASK_OPTS)
        def generate_payslips_batch_task(
            self,
            run_id_str: str,
            employee_ids: list[str],
            force: bool,
            format_type: str,
            job_id: str,
            company_id_str: str | None = None,
            actor_id_str: str | None = None,
            actor_role: str | None = None,
            require_finalized: bool = False,
        ):
            return _execute_celery_coro(
                self,
                _async_generate_payslips_batch(
                    run_id_str,
                    employee_ids,
                    force,
                    format_type,
                    job_id,
                    company_id_str=company_id_str,
                    actor_id_str=actor_id_str,
                    actor_role=actor_role,
                    require_finalized=require_finalized,
                ),
                task_label="generate_payslips_batch_task",
            )

        @celery_app.task(name="app.workers.payroll_tasks.deliver_payslips_task", **_TASK_OPTS)
        def deliver_payslips_task(
            self,
            run_id_str: str,
            employee_ids: list[str],
            channels: list[str],
            password_rule: str | None,
            is_password_protected: bool,
            job_id: str,
            company_id_str: str | None = None,
        ):
            return _execute_celery_coro(
                self,
                _async_deliver_payslips(
                    run_id_str,
                    employee_ids,
                    channels,
                    password_rule,
                    is_password_protected,
                    job_id,
                    company_id_str=company_id_str,
                ),
                task_label="deliver_payslips_task",
            )

        @celery_app.task(name="app.workers.payroll_tasks.generate_bank_file_task", **_TASK_OPTS)
        def generate_bank_file_task(self, batch_id_str: str, file_format: str, job_id: str):
            return _execute_celery_coro(
                self,
                _async_generate_bank_file(batch_id_str, file_format, job_id),
                task_label="generate_bank_file_task",
            )

        @celery_app.task(name="app.workers.payroll_tasks.export_payroll_report_task", **_TASK_OPTS)
        def export_payroll_report_task(
            self,
            export_id_str: str,
            report_key: str,
            file_format: str,
            filters: dict,
            job_id: str,
            company_id_str: str | None = None,
        ):
            return _execute_celery_coro(
                self,
                _async_export_payroll_report(
                    export_id_str,
                    report_key,
                    file_format,
                    filters,
                    job_id,
                    company_id_str=company_id_str,
                ),
                task_label="export_payroll_report_task",
            )

        @celery_app.task(name="app.workers.payroll_tasks.generate_statutory_report_task", **_TASK_OPTS)
        def generate_statutory_report_task(self, component: str, period_id_str: str, file_format: str, job_id: str):
            return _execute_celery_coro(
                self,
                _async_generate_statutory_report(component, period_id_str, file_format, job_id),
                task_label="generate_statutory_report_task",
            )

except Exception as e:
    logger.warning("Could not register Celery tasks for payroll: %s", e)


# ── Async Task Execution Logic ───────────────────────────────────────────────

@asynccontextmanager
async def _payroll_worker_session():
    # Each Celery invocation owns its event loop. A pooled asyncpg connection
    # from an earlier asyncio.run cannot be reused on the next task's loop.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.db.database import get_asyncpg_connection

    engine = create_async_engine(settings.DATABASE_URL, async_creator=get_asyncpg_connection, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def _async_recover_abandoned_payroll_runs():
    from app.services.payroll.run_service import PayrollRunService

    async with _payroll_worker_session() as session:
        return await PayrollRunService.recover_abandoned_runs(session)


async def _async_process_payroll_run(run_id_str: str, job_id: str, company_id_str: str | None = None):
    """Core calculation engine execution."""
    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=10)
    try:
        from app.services.payroll.run_service import PayrollRunService
        async with _payroll_worker_session() as session:
            run = await PayrollRunService.execute_run_calculation(
                session, uuid.UUID(run_id_str),
                company_id=uuid.UUID(company_id_str) if company_id_str else None,
                allow_completed=True,
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                processed=run.total_employees if run else 0,
                result={"run_id": run_id_str, "status": run.status if run else "PROCESSED"},
            )
            return {"run_id": run_id_str, "status": run.status}
    except Exception as e:
        from fastapi import HTTPException
        if isinstance(e, HTTPException) and e.status_code == 409:
            from app.services.payroll.run_service import PayrollRunService
            async with _payroll_worker_session() as session:
                run = await PayrollRunService.get_run(
                    session, uuid.UUID(run_id_str),
                    company_id=uuid.UUID(company_id_str) if company_id_str else None,
                )
                # Handle both active processing and already-completed runs.
                # A duplicate worker may arrive after the original has already finished.
                completed_states = {"PROCESSED", "PENDING_APPROVAL", "APPROVED", "FINALIZED", "LOCKED", "PAID"}
                if run.status == "PROCESSING" or run.status in completed_states:
                    return {"run_id": run_id_str, "status": run.status}
        logger.exception("Error processing payroll run %s: %s", run_id_str, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))
        raise


async def _async_generate_payslips_batch(
    run_id_str: str,
    employee_ids: list[str],
    force: bool,
    format_type: str,
    job_id: str,
    company_id_str: str | None = None,
    actor_id_str: str | None = None,
    actor_role: str | None = None,
    require_finalized: bool = False,
):
    """Batch generate payslip PDFs."""
    existing_job = await PayrollJobTracker.get_job(job_id)
    if existing_job and existing_job.get("status") == "COMPLETED":
        logger.info("Skipping duplicate payslip generation execution for already completed job_id=%s", job_id)
        return existing_job.get("result")

    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=15)
    try:
        from app.services.payroll.payslip_service import PayslipService
        async with _payroll_worker_session() as session:
            count = await PayslipService.generate_batch_payslips(
                session,
                uuid.UUID(run_id_str),
                employee_ids,
                force,
                format_type,
                company_id=uuid.UUID(company_id_str) if company_id_str else None,
                actor_id=uuid.UUID(actor_id_str) if actor_id_str else None,
                actor_role=actor_role,
                require_finalized=require_finalized,
            )
            result = {"run_id": run_id_str, "generated_count": count}
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                processed=count,
                result=result,
            )
            return result
    except Exception as e:
        logger.exception("Error generating payslips for run %s (job_id=%s): %s", run_id_str, job_id, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))
        raise


async def _async_deliver_payslips(
    run_id_str: str,
    employee_ids: list[str],
    channels: list[str],
    password_rule: str | None,
    is_password_protected: bool,
    job_id: str,
    company_id_str: str | None = None,
):
    """Deliver payslips and persist per-channel delivery outcomes."""
    existing_job = await PayrollJobTracker.get_job(job_id)
    if existing_job and existing_job.get("status") == "COMPLETED":
        logger.info("Skipping duplicate payslip delivery execution for already completed job_id=%s", job_id)
        return existing_job.get("result")

    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=10)
    try:
        from app.services.payroll.payslip_service import PayslipService
        async with _payroll_worker_session() as session:
            result = await PayslipService.deliver_payslips(
                session,
                uuid.UUID(run_id_str),
                employee_ids,
                channels,
                password_rule,
                is_password_protected,
                company_id=uuid.UUID(company_id_str) if company_id_str else None,
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                total=result["total"],
                processed=result["total"] - result["failed"],
                failed=result["failed"],
                result=result,
            )
            return result
    except Exception as e:
        logger.exception("Error delivering payslips for run %s (job_id=%s): %s", run_id_str, job_id, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))
        raise


async def _async_generate_bank_file(batch_id_str: str, file_format: str, job_id: str):
    """Generate Bank Advice File."""
    existing_job = await PayrollJobTracker.get_job(job_id)
    if existing_job and existing_job.get("status") == "COMPLETED":
        logger.info("Skipping duplicate bank file generation for already completed job_id=%s", job_id)
        return existing_job.get("result")

    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=20)
    try:
        from app.services.payroll.payment_batch_service import PaymentBatchService
        async with _payroll_worker_session() as session:
            bank_file = await PaymentBatchService.generate_bank_file(
                session, uuid.UUID(batch_id_str), file_format
            )
            result = {"bank_file_id": str(bank_file.id), "file_name": bank_file.file_name}
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                result=result,
            )
            return result
    except Exception as e:
        logger.exception("Error generating bank file for batch %s (job_id=%s): %s", batch_id_str, job_id, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))
        raise


async def _async_export_payroll_report(
    export_id_str: str,
    report_key: str,
    file_format: str,
    filters: dict,
    job_id: str,
    company_id_str: str | None = None,
):
    """Export report to CSV/XLSX."""
    existing_job = await PayrollJobTracker.get_job(job_id)
    if existing_job and existing_job.get("status") == "COMPLETED":
        logger.info("Skipping duplicate report export for already completed job_id=%s", job_id)
        return existing_job.get("result")

    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=25)
    try:
        from app.services.payroll.report_service import PayrollReportService
        c_uuid = uuid.UUID(company_id_str) if company_id_str else None
        async with _payroll_worker_session() as session:
            export_rec = await PayrollReportService.generate_export(
                session,
                uuid.UUID(export_id_str),
                report_key,
                file_format,
                filters,
                company_id=c_uuid,
            )
            result = {"export_id": export_id_str, "file_name": export_rec.file_name}
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                result=result,
            )
            return result
    except Exception as e:
        logger.exception("Error generating report export %s (job_id=%s): %s", export_id_str, job_id, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))
        raise


async def _async_generate_statutory_report(
    component: str, period_id_str: str, file_format: str, job_id: str
):
    """Generate statutory authority file."""
    existing_job = await PayrollJobTracker.get_job(job_id)
    if existing_job and existing_job.get("status") == "COMPLETED":
        logger.info("Skipping duplicate statutory report generation for already completed job_id=%s", job_id)
        return existing_job.get("result")

    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=25)
    try:
        from app.services.payroll.statutory_service import StatutoryService
        async with _payroll_worker_session() as session:
            res = await StatutoryService.generate_report_file(
                session, component, uuid.UUID(period_id_str), file_format
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                result=res,
            )
            return res
    except Exception as e:
        logger.exception("Error generating statutory report for %s (job_id=%s): %s", component, job_id, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))
        raise


def _send_or_fallback(
    task_name: str,
    task_args: list[Any],
    job_id: str,
    fallback_coro_factory: Any,
) -> str:
    """Enqueue Celery task with deterministic task_id, or run tracked local asyncio fallback in dev."""
    if settings.USE_CELERY:
        from app.workers.celery_app import CELERY_AVAILABLE, celery_app
        if not CELERY_AVAILABLE or celery_app is None:
            msg = f"USE_CELERY=true but celery package is unavailable for task {task_name}"
            logger.error(msg)
            if settings.is_production:
                from fastapi import HTTPException
                raise HTTPException(status_code=503, detail="Background worker queue is not available.")
        else:
            try:
                celery_app.send_task(
                    task_name,
                    args=task_args,
                    task_id=job_id,
                )
                return job_id
            except Exception as exc:
                logger.error("Celery broker dispatch failed for %s (job_id=%s): %s", task_name, job_id, exc)
                if settings.is_production:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=503,
                        detail="Background task broker unavailable; task could not be queued.",
                    ) from exc
                logger.warning("Dev fallback: scheduling %s via tracked in-process asyncio task (job_id=%s)", task_name, job_id)

    _schedule_fallback_task(fallback_coro_factory(), name=f"{task_name}:{job_id}")
    return job_id


# ── Unified Dispatchers (Celery or Async fallback) ───────────────────────────

async def dispatch_payroll_run_process(run_id: uuid.UUID, company_id: uuid.UUID | None = None) -> str:
    cid_str = str(company_id) if company_id else None
    job_id = await PayrollJobTracker.create_job("payroll_process", {"run_id": str(run_id), "company_id": cid_str})
    return _send_or_fallback(
        "app.workers.payroll_tasks.process_payroll_run_task",
        [str(run_id), job_id, cid_str],
        job_id,
        lambda: _async_process_payroll_run(str(run_id), job_id, cid_str),
    )


dispatch_payroll_processing = dispatch_payroll_run_process


async def dispatch_payslip_generation(
    run_id: uuid.UUID,
    employee_ids: list[str] | None = None,
    force: bool = False,
    format_type: str = "pdf",
    *,
    company_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    require_finalized: bool = False,
) -> str:
    emp_ids = employee_ids or []
    cid_str = str(company_id) if company_id else None
    uid_str = str(actor_id) if actor_id else None
    job_id = await PayrollJobTracker.create_job("payslip_generation", {"run_id": str(run_id), "company_id": cid_str})
    return _send_or_fallback(
        "app.workers.payroll_tasks.generate_payslips_batch_task",
        [str(run_id), emp_ids, force, format_type, job_id, cid_str, uid_str, actor_role, require_finalized],
        job_id,
        lambda: _async_generate_payslips_batch(
            str(run_id),
            emp_ids,
            force,
            format_type,
            job_id,
            company_id_str=cid_str,
            actor_id_str=uid_str,
            actor_role=actor_role,
            require_finalized=require_finalized,
        ),
    )


async def dispatch_payslip_delivery(
    run_id: uuid.UUID,
    employee_ids: list[str] | None = None,
    channels: list[str] | None = None,
    password_rule: str | None = None,
    is_password_protected: bool = True,
    *,
    company_id: uuid.UUID | None = None,
) -> str:
    emp_ids = employee_ids or []
    selected_channels = channels or ["email", "whatsapp"]
    cid_str = str(company_id) if company_id else None
    job_id = await PayrollJobTracker.create_job(
        "payslip_delivery", {"run_id": str(run_id), "channels": selected_channels, "company_id": cid_str}
    )
    return _send_or_fallback(
        "app.workers.payroll_tasks.deliver_payslips_task",
        [str(run_id), emp_ids, selected_channels, password_rule, is_password_protected, job_id, cid_str],
        job_id,
        lambda: _async_deliver_payslips(
            str(run_id),
            emp_ids,
            selected_channels,
            password_rule,
            is_password_protected,
            job_id,
            company_id_str=cid_str,
        ),
    )


# Explicit alias for callers that use the feature name.
dispatch_payslip_deliveries = dispatch_payslip_delivery


async def dispatch_bank_file_generation(
    batch_id: uuid.UUID | str, file_format: str, user_id: Optional[str] = None
) -> str:
    job_id = await PayrollJobTracker.create_job("bank_file_generation", {"batch_id": str(batch_id)})
    return _send_or_fallback(
        "app.workers.payroll_tasks.generate_bank_file_task",
        [str(batch_id), file_format, job_id],
        job_id,
        lambda: _async_generate_bank_file(str(batch_id), file_format, job_id),
    )


async def dispatch_report_export(
    export_id: uuid.UUID,
    report_key: str,
    file_format: str,
    filters: dict,
    company_id: uuid.UUID | None = None,
) -> str:
    cid_str = str(company_id) if company_id else None
    safe_filters = dict(filters or {})
    if cid_str and "company_id" not in safe_filters:
        safe_filters["company_id"] = cid_str
    job_id = await PayrollJobTracker.create_job("report_export", {"export_id": str(export_id), "company_id": cid_str})
    return _send_or_fallback(
        "app.workers.payroll_tasks.export_payroll_report_task",
        [str(export_id), report_key, file_format, safe_filters, job_id, cid_str],
        job_id,
        lambda: _async_export_payroll_report(
            str(export_id), report_key, file_format, safe_filters, job_id, company_id_str=cid_str
        ),
    )


async def dispatch_statutory_report(
    component: str, period_id: uuid.UUID, file_format: str
) -> str:
    job_id = await PayrollJobTracker.create_job("statutory_report", {"component": component})
    return _send_or_fallback(
        "app.workers.payroll_tasks.generate_statutory_report_task",
        [component, str(period_id), file_format, job_id],
        job_id,
        lambda: _async_generate_statutory_report(component, str(period_id), file_format, job_id),
    )
