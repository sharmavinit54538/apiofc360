"""Child process used only by the disposable PostgreSQL crash tests."""

import asyncio
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.payroll.run_service import PayrollRunService


async def main():
    run_id, stage, marker = uuid.UUID(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    url = os.environ["PAYROLL_POSTGRES_TEST_URL"]
    if "payroll_verify" not in url:
        raise RuntimeError("Crash helper requires an explicitly disposable payroll_verify database")
    engine = create_async_engine(url, poolclass=NullPool)

    async def barrier():
        marker.write_text(stage, encoding="utf-8")
        await asyncio.Event().wait()

    original_lock = PayrollRunService._lock_processing_claim
    original_advance = PayrollRunService._advance_deduction_for_employee
    original_commit = AsyncSession.commit
    commits = 0

    async def lock(cls, session, current_id, token, company_id=None):
        if stage == "after_claim":
            await barrier()
        return await original_lock(session, current_id, token, company_id)

    async def advance(cls, session, run, employee_id):
        result = await original_advance(session, run, employee_id)
        if stage == "during_calculation":
            await session.flush()
            await barrier()
        return result

    async def commit(session):
        nonlocal commits
        commits += 1
        if commits == 2 and stage == "before_commit":
            await session.flush()
            await barrier()
        await original_commit(session)
        if commits == 2 and stage == "after_commit":
            await barrier()

    PayrollRunService._lock_processing_claim = classmethod(lock)
    PayrollRunService._advance_deduction_for_employee = classmethod(advance)
    AsyncSession.commit = commit
    if stage == "before_processing":
        await barrier()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await PayrollRunService.execute_run_calculation(session, run_id)


if __name__ == "__main__":
    asyncio.run(main())
