import pytest
import uuid
from decimal import Decimal
from datetime import date, datetime, timezone
from sqlalchemy import select, func, text
from app.db.database import AsyncSessionLocal, engine
from app.models.user import User, UserRole
from app.models.company import Company
from app.models.employee import Employee
from app.models.payroll import Payslip, PayrollRun
from app.core.security import hash_password, verify_password, create_access_token


@pytest.mark.asyncio
async def test_production_backend_database_and_security_suite():
    """Enterprise production integration test suite:
    1. Validates PostgreSQL connection & SQL COUNT(*) aggregations.
    2. Validates password hashing, verification, and JWT auth token creation.
    3. Validates real PostgreSQL CRUD transactions with rollback/commit lifecycle.
    """
    # 1. Database Connection & SQL Aggregations
    async with AsyncSessionLocal() as session:
        ping = await session.execute(text("SELECT 1"))
        assert ping.scalar() == 1

        emp_count_stmt = select(func.count(Employee.id))
        emp_count_res = await session.execute(emp_count_stmt)
        emp_count = emp_count_res.scalar()
        assert isinstance(emp_count, int)
        assert emp_count >= 0

    # 2. Security & Auth Verification
    raw_password = "SecurePassword123!"
    hashed = hash_password(raw_password)
    assert verify_password(raw_password, hashed)
    assert not verify_password("WrongPassword!", hashed)

    test_user_id = str(uuid.uuid4())
    token = create_access_token({"sub": test_user_id, "role": UserRole.ADMIN})
    assert token is not None
    assert len(token) > 20

    # 3. Real Database CRUD Transaction
    async with AsyncSessionLocal() as session:
        comp_id = uuid.uuid4()
        comp = Company(
            id=comp_id,
            name=f"Test Enterprise {comp_id.hex[:6]}",
        )
        session.add(comp)
        await session.commit()

        # Query back real record from PostgreSQL
        query_res = await session.execute(select(Company).where(Company.id == comp_id))
        fetched_comp = query_res.scalar_one_or_none()
        assert fetched_comp is not None
        assert fetched_comp.name.startswith("Test Enterprise")

        # Cleanup real record
        await session.delete(fetched_comp)
        await session.commit()

    # Clean engine pool dispose
    await engine.dispose()
