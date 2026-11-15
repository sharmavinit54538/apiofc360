"""Real PostgreSQL ownership, fencing, rollback, replay and process-kill tests.

PAYROLL_POSTGRES_TEST_URL must name a disposable database. Child-process
termination tests are genuine OS kills, not claims of Celery broker redelivery.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from test_payroll_postgres_concurrency import _seed_run, pg_sessions  # noqa: F401
from app.models.payroll import AdvanceLoan, AdvanceLoanInstallment, PayrollAuditLog, PayrollRun, Payslip
from app.models.payroll_models import PayrollRunEmployee
from app.services.payroll.run_service import PayrollRunService

pytestmark = pytest.mark.asyncio


async def _abandon(factory, run_id):
    token = uuid.uuid4()
    async with factory() as session:
        await session.execute(update(PayrollRun).where(PayrollRun.id == run_id).values(
            status="PROCESSING", processing_token=token,
            processing_lease_until=datetime.now(UTC) - timedelta(minutes=1),
        ))
        await session.commit()
    return token


async def _single_posting(factory, run_id):
    async with factory() as session:
        run = await session.get(PayrollRun, run_id)
        assert run.status == "PROCESSED"
        assert run.processing_token is None and run.processing_lease_until is None
        assert await session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)) == 1
        assert await session.scalar(select(func.count(PayrollRunEmployee.id)).where(PayrollRunEmployee.run_id == run_id)) == 1
        await PayrollRunService.verify_committed_run(session, run)


async def test_abandoned_claim_is_tenant_scoped_audited_and_retryable(pg_sessions):
    company, _, run_id, _ = await _seed_run(pg_sessions)
    token = await _abandon(pg_sessions, run_id)
    async with pg_sessions() as session:
        assert await PayrollRunService.recover_abandoned_runs(session, company_id=uuid.uuid4()) == []
        assert await PayrollRunService.recover_abandoned_runs(session, company_id=company) == [str(run_id)]
        audit = (await session.execute(select(PayrollAuditLog).where(
            PayrollAuditLog.entity_id == run_id, PayrollAuditLog.action == "PROCESSING_ABANDONED",
        ))).scalar_one()
        assert audit.company_id == company and audit.extra_data["claim_token"] == str(token)
        await PayrollRunService.retry_run(session, run_id)
    await _single_posting(pg_sessions, run_id)


async def test_active_transaction_cannot_be_stolen_and_old_owner_is_fenced(pg_sessions):
    company, _, run_id, _ = await _seed_run(pg_sessions)
    old_token = await _abandon(pg_sessions, run_id)
    async with pg_sessions() as owner, pg_sessions() as recovery:
        await PayrollRunService._lock_processing_claim(owner, run_id, old_token, company)
        assert await PayrollRunService.recover_abandoned_runs(recovery, company_id=company) == []
        await owner.rollback()
        assert await PayrollRunService.recover_abandoned_runs(recovery, company_id=company) == [str(run_id)]
        with pytest.raises(HTTPException, match="ownership changed"):
            await PayrollRunService._lock_processing_claim(owner, run_id, old_token, company)
    new_token = await _abandon(pg_sessions, run_id)
    async with pg_sessions() as session:
        assert not await PayrollRunService.mark_processing_failed(session, run_id, claim_token=old_token)
        run = await session.get(PayrollRun, run_id)
        assert run.status == "PROCESSING" and run.processing_token == new_token


async def test_duplicate_worker_delivery_and_successful_replay_do_not_post_again(pg_sessions, monkeypatch):
    from app.workers import payroll_tasks

    company, _, run_id, _ = await _seed_run(pg_sessions)

    @asynccontextmanager
    async def session_factory():
        async with pg_sessions() as session:
            yield session

    monkeypatch.setattr(payroll_tasks, "_payroll_worker_session", session_factory)
    monkeypatch.setattr(payroll_tasks.PayrollJobTracker, "update_job", AsyncMock())
    results = await asyncio.gather(*(
        payroll_tasks._async_process_payroll_run(str(run_id), f"job-{index}", str(company))
        for index in range(5)
    ))
    assert all(row["status"] in {"PROCESSING", "PROCESSED"} for row in results)
    repeated = await payroll_tasks._async_process_payroll_run(str(run_id), "redelivery", str(company))
    assert repeated["status"] == "PROCESSED"
    await _single_posting(pg_sessions, run_id)
    async with pg_sessions() as session:
        assert await session.scalar(select(func.count(PayrollAuditLog.id)).where(
            PayrollAuditLog.entity_id == run_id, PayrollAuditLog.action == "CALCULATION_COMMITTED",
        )) == 1


async def test_exception_after_claim_is_failed_and_retryable(pg_sessions, monkeypatch):
    _, _, run_id, _ = await _seed_run(pg_sessions)
    original = PayrollRunService._lock_processing_claim
    monkeypatch.setattr(PayrollRunService, "_lock_processing_claim", AsyncMock(side_effect=TimeoutError("timeout")))
    async with pg_sessions() as session:
        with pytest.raises(TimeoutError):
            await PayrollRunService.execute_run_calculation(session, run_id)
        run = await session.get(PayrollRun, run_id)
        assert run.status == "FAILED" and run.processing_token is None
        monkeypatch.setattr(PayrollRunService, "_lock_processing_claim", original)
        await PayrollRunService.retry_run(session, run_id)
    await _single_posting(pg_sessions, run_id)


async def test_committed_rows_are_reviewed_instead_of_recalculated(pg_sessions):
    company, _, run_id, employee = await _seed_run(pg_sessions)
    await _abandon(pg_sessions, run_id)
    async with pg_sessions() as session:
        session.add(PayrollRunEmployee(run_id=run_id, employee_id=employee, company_id=company))
        await session.commit()
        assert await PayrollRunService.recover_abandoned_runs(session, company_id=company) == [str(run_id)]
        with pytest.raises(HTTPException, match="manual reconciliation"):
            await PayrollRunService.retry_run(session, run_id)


@pytest.mark.parametrize("stage", ["before_processing", "after_claim", "during_calculation", "before_commit", "after_commit"])
async def test_real_process_kill_rollback_recovery_and_replay(pg_sessions, tmp_path, stage):
    company, _, run_id, employee = await _seed_run(pg_sessions)
    loan_id = uuid.uuid4()
    async with pg_sessions() as session:
        session.add(AdvanceLoan(id=loan_id, company_id=company, employee_id=employee,
            principal_amount=Decimal("3000"), outstanding_balance=Decimal("3000"),
            emi_amount=Decimal("1000"), total_installments=3, installments_paid=0,
            start_from_month=9, start_from_year=2026, status="ACTIVE"))
        await session.commit()
    marker = tmp_path / "reached.txt"
    log_path = tmp_path / "child.log"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd()) + os.pathsep + environment.get("PYTHONPATH", "")
    with log_path.open("w", encoding="utf-8") as output:
        child = subprocess.Popen([sys.executable, "tests/payroll_crash_child.py", str(run_id), stage, str(marker)],
            env=environment, stdout=output, stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                if marker.exists():
                    break
                if child.poll() is not None:
                    pytest.fail(log_path.read_text(encoding="utf-8"))
                await asyncio.sleep(0.1)
            assert marker.exists(), "Child did not reach crash boundary"
            child.kill()
            await asyncio.to_thread(child.wait, timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                await asyncio.to_thread(child.wait, timeout=10)

    async with pg_sessions() as session:
        run = await session.get(PayrollRun, run_id)
        if stage == "after_commit":
            assert run.status == "PROCESSED"
        elif stage == "before_processing":
            assert run.status == "VALIDATED"
        else:
            assert run.status == "PROCESSING"
            assert await session.scalar(select(func.count(Payslip.id)).where(Payslip.payroll_run_id == run_id)) == 0
            assert await session.scalar(select(func.count(AdvanceLoanInstallment.id)).where(AdvanceLoanInstallment.loan_id == loan_id)) == 0
            loan = await session.get(AdvanceLoan, loan_id)
            assert loan.outstanding_balance == Decimal("3000")
            # Advance the recovery evaluation clock; do not change financial rows.
            await session.rollback()
            assert await PayrollRunService.recover_abandoned_runs(
                session, company_id=company, now=datetime.now(UTC) + timedelta(minutes=16),
            ) == [str(run_id)]
            await PayrollRunService.retry_run(session, run_id)
        if stage in {"before_processing", "after_commit"}:
            await PayrollRunService.execute_run_calculation(session, run_id, allow_completed=True)
    await _single_posting(pg_sessions, run_id)
    async with pg_sessions() as session:
        assert await session.scalar(select(func.count(AdvanceLoanInstallment.id)).where(AdvanceLoanInstallment.loan_id == loan_id)) == 1
        loan = await session.get(AdvanceLoan, loan_id)
        assert loan.outstanding_balance == Decimal("2000") and loan.installments_paid == 1
