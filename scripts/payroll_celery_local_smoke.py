"""Real Celery process delivery/replay using a disposable SQLite broker.

This verifies task serialization and a separate worker process, not Redis or
RabbitMQ visibility-timeout redelivery or a production-supported Windows pool.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


async def seed():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from test_payroll_postgres_concurrency import _seed_run
    engine = create_async_engine(os.environ["PAYROLL_POSTGRES_TEST_URL"], poolclass=NullPool)
    try:
        return await _seed_run(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


async def verify(run_id):
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.models.payroll import PayrollRun, Payslip, PayrollAuditLog
    from app.models.payroll_models import PayrollRunEmployee
    from app.services.payroll.run_service import PayrollRunService
    engine = create_async_engine(os.environ["PAYROLL_POSTGRES_TEST_URL"], poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            run = await session.get(PayrollRun, run_id)
            await PayrollRunService.verify_committed_run(session, run)
            counts = {
                "payslips": await session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)),
                "postings": await session.scalar(select(func.count(PayrollRunEmployee.id)).where(PayrollRunEmployee.run_id == run_id)),
                "commits": await session.scalar(select(func.count(PayrollAuditLog.id)).where(
                    PayrollAuditLog.entity_id == run_id, PayrollAuditLog.action == "CALCULATION_COMMITTED")),
            }
            assert run.status == "PROCESSED" and counts == {"payslips": 1, "postings": 1, "commits": 1}, counts
            return counts
    finally:
        await engine.dispose()


def main():
    url = os.environ.get("PAYROLL_POSTGRES_TEST_URL", "")
    if os.environ.get("PAYROLL_TEST_DISPOSABLE") != "1" or "@127.0.0.1:55441/payroll_verify_" not in url:
        raise RuntimeError("Requires the isolated disposable PostgreSQL cluster")
    directory = ROOT / "scratch" / "payroll-verification-20261115" / ("celery-" + uuid.uuid4().hex)
    directory.mkdir()
    broker = "sqla+sqlite:///" + (directory / "broker.sqlite").as_posix()
    backend = "db+sqlite:///" + (directory / "results.sqlite").as_posix()
    os.environ.update(CELERY_BROKER_URL=broker, CELERY_RESULT_BACKEND=backend, USE_CELERY="true")
    company, _, run_id, _ = asyncio.run(seed())
    from app.workers.celery_app import celery_app
    from app.workers.payroll_tasks import process_payroll_run_task
    queue = "payroll_verify_" + uuid.uuid4().hex
    command = [sys.executable, "-m", "celery", "-A", "app.workers.celery_app:celery_app", "worker",
               "--pool=solo", "--concurrency=1", "--without-gossip", "--without-mingle",
               "--without-heartbeat", "--loglevel=INFO", "-Q", queue]
    with (directory / "worker.log").open("w", encoding="utf-8") as output:
        worker = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdout=output,
                                  stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            results = [process_payroll_run_task.apply_async(
                args=[str(run_id), f"delivery-{index}", str(company)], queue=queue) for index in range(3)]
            deadline = time.monotonic() + 180
            while not all(result.ready() for result in results):
                if worker.poll() is not None:
                    raise RuntimeError((directory / "worker.log").read_text(encoding="utf-8"))
                if time.monotonic() > deadline:
                    raise TimeoutError("Celery delivery did not finish within 180 seconds")
                time.sleep(1)
            outcomes = [result.get(timeout=5) for result in results]
            assert all(result["status"] == "PROCESSED" for result in outcomes), outcomes
            counts = asyncio.run(verify(run_id))
            print(json.dumps({"broker": "Kombu SQLite", "worker_pool": "solo", "deliveries": 3,
                              "run_id": str(run_id), "counts": counts, "worker_log": str(directory / "worker.log"),
                              "redis_rabbitmq_crash_redelivery_verified": False}, indent=2))
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=10)
            celery_app.close()


if __name__ == "__main__":
    main()
