"""PostgreSQL-only claim and failure-recovery integration tests.

Run only with PAYROLL_POSTGRES_TEST_URL pointing to a disposable PostgreSQL
database. The test fixture creates the model schema in that database; it never
reads the application's DATABASE_URL.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.asyncio
TEST_DATABASE_URL = os.getenv("PAYROLL_POSTGRES_TEST_URL")


@pytest_asyncio.fixture(scope="session")
async def pg_sessions():
    if not TEST_DATABASE_URL:
        pytest.skip("PAYROLL_POSTGRES_TEST_URL must point to a disposable PostgreSQL database")
    if not TEST_DATABASE_URL.startswith("postgresql+asyncpg://"):
        pytest.fail("PAYROLL_POSTGRES_TEST_URL must use postgresql+asyncpg")

    import app.models  # noqa: F401 - register all model metadata
    from app.db.base import Base

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        # Schema already applied by alembic upgrade head; do not call create_all
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _seed_run(session_factory):
    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.payroll import PayrollRun, StatutoryComplianceConfig
    from app.models.payroll_models import Compensation, PayrollPeriod

    company_id = uuid.uuid4()
    period_id = uuid.uuid4()
    run_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    async with session_factory() as session:
        company = Company(id=company_id, name=f"Concurrency Test {company_id.hex[:8]}")
        employee = Employee(
            id=employee_id, company_id=company_id,
            employee_id=f"PGEMP-{employee_id.hex[:12]}", first_name="Test",
            last_name="Employee", personal_email=f"{employee_id.hex}@example.test",
            phone="9876543210", department="Payroll Test", designation="Test",
            joining_date=date(2024, 1, 1), status="ACTIVE", is_deleted=False,
        )
        compensation = Compensation(
            id=uuid.uuid4(), company_id=company_id, employee_id=employee_id,
            ctc_annual_paise=57_600_000, basic_monthly_paise=3_000_000,
            hra_monthly_paise=1_200_000, special_allowance_monthly_paise=600_000,
            status="ACTIVE", effective_date=date(2020, 1, 1),
        )
        config = StatutoryComplianceConfig(
            company_id=company_id, is_active=True, effective_from=date(2020, 1, 1),
            pf_enabled=False, esi_enabled=False, pt_state="MAHARASHTRA", pt_slabs=[],
        )
        period = PayrollPeriod(
            id=period_id, company_id=company_id, name=f"Test {period_id.hex[:8]}",
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
            pay_date=date(2026, 9, 30), period_month=9, period_year=2026,
            status="OPEN",
        )
        run = PayrollRun(
            id=run_id, company_id=company_id, period_id=period_id,
            run_number=f"PG-{run_id.hex[:12]}", period_month=9, period_year=2026,
            status="VALIDATED",
        )
        session.add_all([company, employee, compensation, config, period, run])
        await session.commit()
    return company_id, period_id, run_id, employee_id


async def _calculate(session_factory, run_id):
    from app.services.payroll.run_service import PayrollRunService

    async with session_factory() as session:
        try:
            result = await PayrollRunService.execute_run_calculation(session, run_id)
            return ("ACCEPTED", result.status)
        except HTTPException as exc:
            if exc.status_code == 409:
                return ("CONFLICT", None)
            raise


@pytest.mark.parametrize("request_count", [2, 5, 10])
async def test_postgres_one_claim_for_simultaneous_requests(pg_sessions, request_count):
    from app.models.payroll import AdvanceLoan, AdvanceLoanInstallment, PayrollRun, Payslip
    from app.models.payroll_models import PaymentBatch, PaymentBatchItem, PayrollRunEmployee

    company_id, _period_id, run_id, employee_id = await _seed_run(pg_sessions)
    results = await asyncio.gather(*(_calculate(pg_sessions, run_id) for _ in range(request_count)))
    assert sum(result[0] == "ACCEPTED" for result in results) == 1
    assert sum(result[0] == "CONFLICT" for result in results) == request_count - 1

    async with pg_sessions() as session:
        run = (await session.execute(select(PayrollRun).where(PayrollRun.id == run_id))).scalar_one()
        assert run.company_id == company_id
        assert run.status == "PROCESSED"
        assert await session.scalar(select(func.count(PayrollRunEmployee.id)).where(
            PayrollRunEmployee.run_id == run_id
        )) == 1
        assert await session.scalar(select(func.count(Payslip.id)).where(
            Payslip.payroll_run_id == run_id
        )) == 1
        assert await session.scalar(select(func.count(AdvanceLoanInstallment.id)).join(
            AdvanceLoan, AdvanceLoanInstallment.loan_id == AdvanceLoan.id,
        ).where(AdvanceLoan.company_id == company_id)) == 0
        batch_count = await session.scalar(select(func.count(PaymentBatch.id)).where(PaymentBatch.run_id == run_id))
        item_count = await session.scalar(select(func.count(PaymentBatchItem.id)).join(
            PaymentBatch, PaymentBatchItem.batch_id == PaymentBatch.id
        ).where(PaymentBatch.run_id == run_id))
        assert batch_count == item_count == 0
        payslip = (await session.execute(select(Payslip).where(
            Payslip.payroll_run_id == run_id
        ))).scalar_one()
        assert payslip.employee_id == employee_id


async def test_postgres_parallel_tenants_and_failure_retry(pg_sessions):
    from app.models.payroll import PayrollAuditLog, PayrollRun, Payslip
    from app.models.payroll_models import PayrollRunEmployee
    from app.services.payroll.run_service import PayrollRunService

    first_company, _first_period, first_run, first_employee = await _seed_run(pg_sessions)
    second_company, _second_period, second_run, second_employee = await _seed_run(pg_sessions)
    first_result, second_result = await asyncio.gather(
        _calculate(pg_sessions, first_run), _calculate(pg_sessions, second_run)
    )
    assert first_result == ("ACCEPTED", "PROCESSED")
    assert second_result == ("ACCEPTED", "PROCESSED")
    async with pg_sessions() as session:
        first_posting = (await session.execute(select(PayrollRunEmployee).where(
            PayrollRunEmployee.run_id == first_run
        ))).scalar_one()
        second_posting = (await session.execute(select(PayrollRunEmployee).where(
            PayrollRunEmployee.run_id == second_run
        ))).scalar_one()
        assert first_posting.company_id == first_company
        assert first_posting.employee_id == first_employee
        assert second_posting.company_id == second_company
        assert second_posting.employee_id == second_employee

    # Model an exception after the committed claim. Recovery persists a failure,
    # then the normal failed-run retry calculates the single seeded employee.
    _company, _period, retry_run, _employee = await _seed_run(pg_sessions)
    async with pg_sessions() as session:
        await session.execute(update(PayrollRun).where(PayrollRun.id == retry_run).values(status="PROCESSING"))
        await session.commit()
        recovered = await PayrollRunService.mark_processing_failed(
            session, retry_run, error_code="SIMULATED_WORKER_EXCEPTION",
            detail="Simulated worker exception after claim.",
        )
        assert recovered is True
        run = (await session.execute(select(PayrollRun).where(PayrollRun.id == retry_run))).scalar_one()
        assert run.status == "FAILED"
        assert run.validation_errors[0]["code"] == "SIMULATED_WORKER_EXCEPTION"
        audit = (await session.execute(select(PayrollAuditLog).where(
            PayrollAuditLog.entity_id == retry_run,
            PayrollAuditLog.action == "CALCULATION_FAILED",
        ))).scalar_one()
        assert audit.company_id == run.company_id

    async with pg_sessions() as session:
        retried = await PayrollRunService.retry_run(session, retry_run)
        assert retried.status == "PROCESSED"
        assert retried.company_id not in {first_company, second_company}  # tenant-local run
        assert await session.scalar(select(func.count(Payslip.id)).where(
            Payslip.payroll_run_id == retry_run
        )) == 1
        assert await session.scalar(select(func.count(PayrollRunEmployee.id)).where(
            PayrollRunEmployee.run_id == retry_run
        )) == 1


async def _lock_test_run_for_payment(session_factory, run_id):
    """Build finalized postings, then place the run in the payment-eligible state."""
    from app.models.payroll import PayrollRun
    from app.services.payroll.run_service import PayrollRunService

    async with session_factory() as session:
        await PayrollRunService.execute_run_calculation(session, run_id)
        await session.execute(update(PayrollRun).where(PayrollRun.id == run_id).values(
            status="LOCKED", is_locked=True,
        ))
        await session.commit()


async def test_postgres_payment_batch_request_replay_returns_persisted_operation(pg_sessions):
    from app.models.payroll_models import PaymentBatch, PaymentBatchItem
    from app.services.payroll.payment_batch_service import PaymentBatchService

    company_id, _period_id, run_id, _employee_id = await _seed_run(pg_sessions)
    await _lock_test_run_for_payment(pg_sessions, run_id)
    async with pg_sessions() as session:
        first = await PaymentBatchService.create_batch_from_run(
            session, run_id, "source-account", "NEFT", company_id=company_id,
        )
        first_id = first.id
    async with pg_sessions() as session:
        replay = await PaymentBatchService.create_batch_from_run(
            session, run_id, "source-account", "NEFT", company_id=company_id,
        )
        assert replay.id == first_id
    async with pg_sessions() as session:
        assert await session.scalar(select(func.count(PaymentBatch.id)).where(
            PaymentBatch.company_id == company_id, PaymentBatch.run_id == run_id,
        )) == 1
        assert await session.scalar(select(func.count(PaymentBatchItem.id)).join(
            PaymentBatch, PaymentBatchItem.batch_id == PaymentBatch.id,
        ).where(PaymentBatch.run_id == run_id)) == 1


@pytest.mark.parametrize("request_count", [2, 5, 10])
async def test_postgres_simultaneous_payment_batch_requests_create_one_batch(pg_sessions, request_count):
    from app.models.payroll_models import PaymentBatch, PaymentBatchItem
    from app.services.payroll.payment_batch_service import PaymentBatchService

    company_id, _period_id, run_id, _employee_id = await _seed_run(pg_sessions)
    await _lock_test_run_for_payment(pg_sessions, run_id)

    async def create():
        async with pg_sessions() as session:
            batch = await PaymentBatchService.create_batch_from_run(
                session, run_id, "source-account", "NEFT", company_id=company_id,
            )
            return batch.id

    batch_ids = await asyncio.gather(*(create() for _ in range(request_count)))
    assert len(set(batch_ids)) == 1
    async with pg_sessions() as session:
        assert await session.scalar(select(func.count(PaymentBatch.id)).where(
            PaymentBatch.company_id == company_id, PaymentBatch.run_id == run_id,
        )) == 1
        assert await session.scalar(select(func.count(PaymentBatchItem.id)).join(
            PaymentBatch, PaymentBatchItem.batch_id == PaymentBatch.id,
        ).where(PaymentBatch.run_id == run_id)) == 1
