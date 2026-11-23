import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.company import Company
from app.core.security import hash_password
from app.core.config import settings

@pytest.mark.asyncio(loop_scope="session")
async def test_rbac_authorization():
    """Verify RBAC scopes for HR Admin vs Employee on user management endpoints."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncSessionLocal() as session:
        # Create company
        comp_id = uuid.uuid4()
        test_company = Company(
            id=comp_id,
            name=f"RBAC Test Corp {comp_id.hex[:6]}",
            onboarding_completed=True,
            onboarding_step=7,
        )
        session.add(test_company)

        # Create HR Admin
        hr_id = uuid.uuid4()
        hr_user = User(
            id=hr_id,
            company_id=comp_id,
            name="HR Admin",
            email=f"hr_{hr_id.hex[:8]}@example.com",
            phone=f"99{hr_id.int % 100000000:08d}",
            password_hash=hash_password("Password@123"),
            role=UserRole.HR_ADMIN,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        )
        session.add(hr_user)

        # Create Employee
        emp_id = uuid.uuid4()
        emp_user = User(
            id=emp_id,
            company_id=comp_id,
            name="Employee",
            email=f"emp_{emp_id.hex[:8]}@example.com",
            phone=f"98{emp_id.int % 100000000:08d}",
            password_hash=hash_password("Password@123"),
            role=UserRole.EMPLOYEE,
            account_status="ACTIVE",
            is_active=True,
            is_verified=True,
        )
        session.add(emp_user)
        await session.commit()

    # Generate secure tokens matching the format expected by the backend
    from app.core.security import create_access_token
    hr_token = create_access_token(
        subject=str(hr_id),
        claims={"role": "hr_admin", "company_id": str(comp_id), "type": "access", "email": "hr@example.com"}
    )
    emp_token = create_access_token(
        subject=str(emp_id),
        claims={"role": "employee", "company_id": str(comp_id), "type": "access", "email": "emp@example.com"}
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. HR Admin CAN access admin endpoint (e.g. creating a user)
        res_hr = await client.post(
            "/api/v1/hr-admin/users",
            headers={"Authorization": f"Bearer {hr_token}"},
            json={
                "first_name": "New", "last_name": "User",
                "email": f"new_{uuid.uuid4().hex[:8]}@example.com",
                "phone": f"97{uuid.uuid4().int % 100000000:08d}",
                "role": "employee"
            }
        )
        assert res_hr.status_code in [201, 200]

        # 2. Employee CANNOT access admin endpoint
        res_emp = await client.post(
            "/api/v1/hr-admin/users",
            headers={"Authorization": f"Bearer {emp_token}"},
            json={
                "first_name": "New", "last_name": "User2",
                "email": f"new2_{uuid.uuid4().hex[:8]}@example.com",
                "phone": f"96{uuid.uuid4().int % 100000000:08d}",
                "role": "employee"
            }
        )
        assert res_emp.status_code in [401, 403]

    # Cleanup
    async with AsyncSessionLocal() as session:
        h = await session.get(User, hr_id)
        e = await session.get(User, emp_id)
        c = await session.get(Company, comp_id)
        if h: await session.delete(h)
        if e: await session.delete(e)
        if c: await session.delete(c)
        await session.commit()
