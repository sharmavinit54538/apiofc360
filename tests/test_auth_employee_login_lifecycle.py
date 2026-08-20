import pytest
import uuid
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User, UserRole, UserAccountStatus
from app.core.security import hash_password
from app.services.employee_service import EmployeeService
from app.schemas.employee import ActivateEmployeeRequest
from app.schemas.hr_admin import HRAdminCreateUserRequest
from app.services.hr_admin_service import HRAdminService
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.services.email_service import EmailService


@pytest.fixture
def test_app():
    return create_app()


@pytest.mark.asyncio
async def test_auth_login_valid_active_employee(test_app):
    """Scenario 1: Valid active employee credentials return 200 OK with tokens and user info."""
    transport = ASGITransport(app=test_app)
    raw_pass = "SecureActivePass@2026"
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_active_{test_id}@example.com"
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"Active Emp Co {test_id}", onboarding_completed=True, onboarding_step=7)
        session.add(comp)

        user = User(
            id=user_id,
            company_id=comp_id,
            name=f"Active Emp {test_id}",
            email=email,
            phone=f"98{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password(raw_pass),
            role=UserRole.EMPLOYEE,
            is_active=True,
            is_verified=True,
            account_status="ACTIVE",
            onboarding_completed=True,
        )
        session.add(user)

        emp = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"EMP-{test_id.upper()}",
            first_name="Active",
            last_name="Tester",
            personal_email=email,
            company_email=email,
            phone="9876543210",
            department="Engineering",
            designation="Software Engineer",
            role="employee",
            status="ACTIVE",
            employment_status="CONFIRMED",
            is_active=True,
            is_deleted=False,
            joining_date=datetime.now(timezone.utc).date(),
        )
        session.add(emp)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": raw_pass},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "access_token" in data["data"]
            assert "refresh_token" in data["data"]
            assert data["data"]["user"]["email"] == email
            assert data["data"]["user"]["role"] == "employee"
            assert data["data"]["user"]["is_verified"] is True
    finally:
        async with AsyncSessionLocal() as session:
            e = await session.get(Employee, emp_id)
            if e:
                await session.delete(e)
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_auth_login_wrong_password(test_app):
    """Scenario 2: Correct identifier with wrong password returns 401 Unauthorized."""
    transport = ASGITransport(app=test_app)
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_wrongpw_{test_id}@example.com"
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"Wrong PW Co {test_id}")
        session.add(comp)
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Wrong PW Tester",
            email=email,
            phone=f"97{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password("CorrectPassword@123"),
            role=UserRole.EMPLOYEE,
            is_active=True,
            is_verified=True,
            account_status="ACTIVE",
        )
        session.add(user)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": "WrongPassword@999"},
            )
            assert resp.status_code == 401
            data = resp.json()
            assert data["success"] is False
    finally:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_auth_login_unverified_user(test_app):
    """Scenario 3: Unverified email user login attempt returns 403 EMAIL_NOT_VERIFIED."""
    transport = ASGITransport(app=test_app)
    raw_pass = "UnverifiedPass@2026"
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_unverified_{test_id}@example.com"
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"Unverified Co {test_id}")
        session.add(comp)
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Unverified Tester",
            email=email,
            phone=f"96{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password(raw_pass),
            role=UserRole.EMPLOYEE,
            is_active=True,
            is_verified=False,
            account_status="PENDING_EMAIL_VERIFICATION",
        )
        session.add(user)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": raw_pass},
            )
            assert resp.status_code == 403
            data = resp.json()
            assert data["success"] is False
            assert data["code"] == "EMAIL_NOT_VERIFIED"
    finally:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_auth_login_inactive_user(test_app):
    """Scenario 4: Inactive user account returns 403 ACCOUNT_INACTIVE."""
    transport = ASGITransport(app=test_app)
    raw_pass = "InactivePass@2026"
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_inactive_user_{test_id}@example.com"
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"Inactive User Co {test_id}")
        session.add(comp)
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Inactive User Tester",
            email=email,
            phone=f"95{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password(raw_pass),
            role=UserRole.EMPLOYEE,
            is_active=False,
            is_verified=True,
            account_status="SUSPENDED",
        )
        session.add(user)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": raw_pass},
            )
            assert resp.status_code == 403
            data = resp.json()
            assert data["success"] is False
            assert data["code"] == "ACCOUNT_INACTIVE"
    finally:
        async with AsyncSessionLocal() as session:
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_auth_login_inactive_employee_profile(test_app):
    """Scenario 5: Active user with deactivated employee profile returns 403 EMPLOYEE_INACTIVE."""
    transport = ASGITransport(app=test_app)
    raw_pass = "DeactivatedProfilePass@2026"
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_inactive_profile_{test_id}@example.com"
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"Inactive Profile Co {test_id}")
        session.add(comp)
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Deactivated Profile Tester",
            email=email,
            phone=f"94{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password(raw_pass),
            role=UserRole.EMPLOYEE,
            is_active=True,
            is_verified=True,
            account_status="ACTIVE",
        )
        session.add(user)

        emp = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"EMP-TERM-{test_id.upper()}",
            first_name="Terminated",
            last_name="Tester",
            personal_email=email,
            company_email=email,
            phone="9400000000",
            department="Operations",
            designation="Officer",
            role="employee",
            status="DEACTIVATED",
            employment_status="TERMINATED",
            is_active=False,
            is_deleted=False,
            joining_date=datetime.now(timezone.utc).date(),
        )
        session.add(emp)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": raw_pass},
            )
            assert resp.status_code == 403
            data = resp.json()
            assert data["success"] is False
            assert data["code"] == "EMPLOYEE_INACTIVE"
    finally:
        async with AsyncSessionLocal() as session:
            e = await session.get(Employee, emp_id)
            if e:
                await session.delete(e)
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_auth_login_successfully_activated_employee(test_app):
    """Scenario 6: Successfully activated employee with ONBOARDING_PENDING status logs in with 200 OK."""
    transport = ASGITransport(app=test_app)
    raw_pass = "ActivatedOnboardingPass@2026"
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_onboarding_pending_{test_id}@example.com"
    comp_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"Activated Onboarding Co {test_id}")
        session.add(comp)
        user = User(
            id=user_id,
            company_id=comp_id,
            name="Activated Onboarding Tester",
            email=email,
            phone=f"93{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password(raw_pass),
            role=UserRole.EMPLOYEE,
            is_active=True,
            is_verified=True,
            account_status="ACTIVE",
            onboarding_completed=False,
        )
        session.add(user)

        emp = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=comp_id,
            employee_id=f"EMP-ONB-{test_id.upper()}",
            first_name="Onboarding",
            last_name="Pending",
            personal_email=email,
            company_email=email,
            phone="9300000000",
            department="Product",
            designation="Associate",
            role="employee",
            status="ONBOARDING_PENDING",
            employment_status="PROBATION",
            is_active=True,
            is_deleted=False,
            joining_date=datetime.now(timezone.utc).date(),
        )
        session.add(emp)
        await session.commit()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": raw_pass},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "access_token" in data["data"]
            assert data["data"]["user"]["email"] == email
            assert data["data"]["user"]["onboarding_completed"] is False
    finally:
        async with AsyncSessionLocal() as session:
            e = await session.get(Employee, emp_id)
            if e:
                await session.delete(e)
            u = await session.get(User, user_id)
            if u:
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()


@pytest.mark.asyncio
async def test_auth_complete_invitation_activation_login_flow(test_app):
    """Scenario 7: Full E2E flow: invitation -> unactivated login fails -> activation -> password setup -> login succeeds (200)."""
    transport = ASGITransport(app=test_app)
    test_id = uuid.uuid4().hex[:8]
    email = f"emp_e2e_{test_id}@example.com"
    comp_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    new_password = "E2EActivatedSecurePass@2026"

    async with AsyncSessionLocal() as session:
        comp = Company(id=comp_id, name=f"E2E Test Corp {test_id}")
        session.add(comp)

        admin_user = User(
            id=admin_id,
            company_id=comp_id,
            name="HR Admin E2E",
            email=f"hr_admin_{test_id}@example.com",
            phone=f"92{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password("AdminPass@123"),
            role=UserRole.HR_ADMIN,
            is_active=True,
            is_verified=True,
            account_status="ACTIVE",
        )
        session.add(admin_user)
        await session.commit()

        # Step 1: Admin creates employee invitation
        hr_svc = HRAdminService(
            session=session,
            auth_repo=AuthRepository(session),
            emp_repo=EmployeeRepository(session),
            email_service=EmailService(),
        )
        create_payload = HRAdminCreateUserRequest(
            first_name="Sunaina",
            last_name="Verma",
            email=email,
            phone="9876501234",
            role="employee",
            department="Design",
            designation="UI/UX Designer",
        )
        user_resp = await hr_svc.create_internal_user(comp_id, admin_id, create_payload)
        assert user_resp.email == email
        assert user_resp.account_status == "INVITED"

        # Lookup employee record to obtain token
        emp_res = await session.execute(
            select(Employee).where(Employee.personal_email == email)
        )
        created_emp = emp_res.scalars().first()
        assert created_emp is not None
        activation_token = created_emp.activation_token
        emp_uuid = created_emp.id
        assert activation_token is not None

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Step 2: Login before activation must fail with 403
            pre_login_resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": new_password},
            )
            # Before setting password, either 401 or 403
            assert pre_login_resp.status_code in (401, 403)

            # Step 3: Employee activates account via canonical activation endpoint
            act_resp = await client.post(
                f"/api/v1/employees/{emp_uuid}/activate",
                json={
                    "token": activation_token,
                    "new_password": new_password,
                    "confirm_password": new_password,
                },
            )
            assert act_resp.status_code == 200
            assert act_resp.json()["success"] is True

            # Step 4: Login after activation must succeed with 200 OK
            post_login_resp = await client.post(
                "/api/v1/auth/login",
                json={"identifier": email, "password": new_password},
            )
            assert post_login_resp.status_code == 200
            login_data = post_login_resp.json()
            assert login_data["success"] is True
            assert "access_token" in login_data["data"]
            assert login_data["data"]["user"]["email"] == email
            assert login_data["data"]["user"]["is_verified"] is True
            assert login_data["data"]["user"]["account_status"] == "ACTIVE"

    finally:
        async with AsyncSessionLocal() as session:
            emp_cleanup = await session.execute(select(Employee).where(Employee.personal_email == email))
            for e in emp_cleanup.scalars().all():
                await session.delete(e)
            user_cleanup = await session.execute(select(User).where(User.email.in_([email, f"hr_admin_{test_id}@example.com"])))
            for u in user_cleanup.scalars().all():
                await session.delete(u)
            c = await session.get(Company, comp_id)
            if c:
                await session.delete(c)
            await session.commit()
