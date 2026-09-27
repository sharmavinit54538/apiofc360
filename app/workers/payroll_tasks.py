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
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from app.core.config import settings
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# Fallback in-memory job store
_IN_MEMORY_JOBS: dict[str, dict[str, Any]] = {}


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
            await redis_client.set(f"{cls.PREFIX}{job_id}", json.dumps(job_data), ttl_seconds=86400)
        except Exception:
            pass
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
            await redis_client.set(f"{cls.PREFIX}{job_id}", json.dumps(job), ttl_seconds=86400)
        except Exception:
            pass

    @classmethod
    async def get_job(cls, job_id: str) -> Optional[dict[str, Any]]:
        if not job_id:
            return None
        try:
            val = await redis_client.get(f"{cls.PREFIX}{job_id}")
            if val:
                return json.loads(val)
        except Exception:
            pass
        return _IN_MEMORY_JOBS.get(job_id)


# ── Celery Task Definitions ──────────────────────────────────────────────────
try:
    from app.workers.celery_app import celery_app, CELERY_AVAILABLE
    if CELERY_AVAILABLE and celery_app is not None:

        @celery_app.task(name="app.workers.payroll_tasks.process_payroll_run_task")
        def process_payroll_run_task(run_id_str: str, job_id: str):
            asyncio.run(_async_process_payroll_run(run_id_str, job_id))

        @celery_app.task(name="app.workers.payroll_tasks.generate_payslips_batch_task")
        def generate_payslips_batch_task(run_id_str: str, employee_ids: list[str], force: bool, format_type: str, job_id: str):
            asyncio.run(_async_generate_payslips_batch(run_id_str, employee_ids, force, format_type, job_id))

        @celery_app.task(name="app.workers.payroll_tasks.generate_bank_file_task")
        def generate_bank_file_task(batch_id_str: str, file_format: str, job_id: str):
            asyncio.run(_async_generate_bank_file(batch_id_str, file_format, job_id))

        @celery_app.task(name="app.workers.payroll_tasks.export_payroll_report_task")
        def export_payroll_report_task(export_id_str: str, report_key: str, file_format: str, filters: dict, job_id: str):
            asyncio.run(_async_export_payroll_report(export_id_str, report_key, file_format, filters, job_id))

        @celery_app.task(name="app.workers.payroll_tasks.generate_statutory_report_task")
        def generate_statutory_report_task(component: str, period_id_str: str, file_format: str, job_id: str):
            asyncio.run(_async_generate_statutory_report(component, period_id_str, file_format, job_id))

except Exception as e:
    logger.warning("Could not register Celery tasks for payroll: %s", e)


# ── Async Task Execution Logic ───────────────────────────────────────────────

async def _async_process_payroll_run(run_id_str: str, job_id: str):
    """Core calculation engine execution."""
    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=10)
    try:
        from app.db.database import AsyncSessionLocal
        from app.services.payroll.run_service import PayrollRunService
        async with AsyncSessionLocal() as session:
            run = await PayrollRunService.execute_run_calculation(session, uuid.UUID(run_id_str))
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                processed=run.total_employees if run else 0,
                result={"run_id": run_id_str, "status": run.status if run else "PROCESSED"},
            )
    except Exception as e:
        logger.exception("Error processing payroll run %s: %s", run_id_str, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))


async def _async_generate_payslips_batch(
    run_id_str: str, employee_ids: list[str], force: bool, format_type: str, job_id: str
):
    """Batch generate payslip PDFs."""
    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=15)
    try:
        from app.db.database import AsyncSessionLocal
        from app.services.payroll.payslip_service import PayslipService
        async with AsyncSessionLocal() as session:
            count = await PayslipService.generate_batch_payslips(
                session, uuid.UUID(run_id_str), employee_ids, force, format_type
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                processed=count,
                result={"run_id": run_id_str, "generated_count": count},
            )
    except Exception as e:
        logger.exception("Error generating payslips for run %s: %s", run_id_str, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))


async def _async_generate_bank_file(batch_id_str: str, file_format: str, job_id: str):
    """Generate Bank Advice File."""
    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=20)
    try:
        from app.db.database import AsyncSessionLocal
        from app.services.payroll.payment_batch_service import PaymentBatchService
        async with AsyncSessionLocal() as session:
            bank_file = await PaymentBatchService.generate_bank_file(
                session, uuid.UUID(batch_id_str), file_format
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                result={"bank_file_id": str(bank_file.id), "file_name": bank_file.file_name},
            )
    except Exception as e:
        logger.exception("Error generating bank file for batch %s: %s", batch_id_str, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))


async def _async_export_payroll_report(
    export_id_str: str, report_key: str, file_format: str, filters: dict, job_id: str
):
    """Export report to CSV/XLSX."""
    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=25)
    try:
        from app.db.database import AsyncSessionLocal
        from app.services.payroll.report_service import PayrollReportService
        async with AsyncSessionLocal() as session:
            export_rec = await PayrollReportService.generate_export(
                session, uuid.UUID(export_id_str), report_key, file_format, filters
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                result={"export_id": export_id_str, "file_name": export_rec.file_name},
            )
    except Exception as e:
        logger.exception("Error generating report export %s: %s", export_id_str, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))


async def _async_generate_statutory_report(
    component: str, period_id_str: str, file_format: str, job_id: str
):
    """Generate statutory authority file."""
    await PayrollJobTracker.update_job(job_id, "PROCESSING", progress=25)
    try:
        from app.db.database import AsyncSessionLocal
        from app.services.payroll.statutory_service import StatutoryService
        async with AsyncSessionLocal() as session:
            res = await StatutoryService.generate_report_file(
                session, component, uuid.UUID(period_id_str), file_format
            )
            await PayrollJobTracker.update_job(
                job_id,
                "COMPLETED",
                progress=100,
                result=res,
            )
    except Exception as e:
        logger.exception("Error generating statutory report for %s: %s", component, e)
        await PayrollJobTracker.update_job(job_id, "FAILED", error=str(e))


# ── Unified Dispatchers (Celery or Async fallback) ───────────────────────────

async def dispatch_payroll_run_process(run_id: uuid.UUID) -> str:
    job_id = await PayrollJobTracker.create_job("payroll_process", {"run_id": str(run_id)})
    if settings.USE_CELERY:
        try:
            from app.workers.celery_app import celery_app
            celery_app.send_task(
                "app.workers.payroll_tasks.process_payroll_run_task",
                args=[str(run_id), job_id],
            )
            return job_id
        except Exception as e:
            logger.warning("Celery dispatch failed, running asyncio background task: %s", e)
    asyncio.create_task(_async_process_payroll_run(str(run_id), job_id))
    return job_id


dispatch_payroll_processing = dispatch_payroll_run_process


async def dispatch_payslip_generation(
    run_id: uuid.UUID,
    employee_ids: list[str] | None = None,
    force: bool = False,
    format_type: str = "pdf",
) -> str:
    emp_ids = employee_ids or []
    job_id = await PayrollJobTracker.create_job("payslip_generation", {"run_id": str(run_id)})
    if settings.USE_CELERY:
        try:
            from app.workers.celery_app import celery_app
            celery_app.send_task(
                "app.workers.payroll_tasks.generate_payslips_batch_task",
                args=[str(run_id), emp_ids, force, format_type, job_id],
            )
            return job_id
        except Exception as e:
            logger.warning("Celery dispatch failed, running asyncio background task: %s", e)
    asyncio.create_task(_async_generate_payslips_batch(str(run_id), emp_ids, force, format_type, job_id))
    return job_id


async def dispatch_bank_file_generation(
    batch_id: uuid.UUID | str, file_format: str, user_id: Optional[str] = None
) -> str:
    job_id = await PayrollJobTracker.create_job("bank_file_generation", {"batch_id": str(batch_id)})
    if settings.USE_CELERY:
        try:
            from app.workers.celery_app import celery_app
            celery_app.send_task(
                "app.workers.payroll_tasks.generate_bank_file_task",
                args=[str(batch_id), file_format, job_id],
            )
            return job_id
        except Exception as e:
            logger.warning("Celery dispatch failed, running asyncio background task: %s", e)
    asyncio.create_task(_async_generate_bank_file(str(batch_id), file_format, job_id))
    return job_id


async def dispatch_report_export(
    export_id: uuid.UUID, report_key: str, file_format: str, filters: dict
) -> str:
    job_id = await PayrollJobTracker.create_job("report_export", {"export_id": str(export_id)})
    if settings.USE_CELERY:
        try:
            from app.workers.celery_app import celery_app
            celery_app.send_task(
                "app.workers.payroll_tasks.export_payroll_report_task",
                args=[str(export_id), report_key, file_format, filters, job_id],
            )
            return job_id
        except Exception as e:
            logger.warning("Celery dispatch failed, running asyncio background task: %s", e)
    asyncio.create_task(_async_export_payroll_report(str(export_id), report_key, file_format, filters, job_id))
    return job_id


async def dispatch_statutory_report(
    component: str, period_id: uuid.UUID, file_format: str
) -> str:
    job_id = await PayrollJobTracker.create_job("statutory_report", {"component": component})
    if settings.USE_CELERY:
        try:
            from app.workers.celery_app import celery_app
            celery_app.send_task(
                "app.workers.payroll_tasks.generate_statutory_report_task",
                args=[component, str(period_id), file_format, job_id],
            )
            return job_id
        except Exception as e:
            logger.warning("Celery dispatch failed, running asyncio background task: %s", e)
    asyncio.create_task(_async_generate_statutory_report(component, str(period_id), file_format, job_id))
    return job_id
