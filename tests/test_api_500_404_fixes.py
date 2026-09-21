"""Comprehensive automated tests for OFC360 API 500/404 Root-Cause Fixes.

Covers:
1. Face Attendance Company View (500 fix): GET /api/v1/attendance/face/company?page=1&limit=20
2. Payroll Cycles (404 fix): GET/POST /v2/payroll/cycles
3. Payroll Salary Processing (404 fix): GET /v2/payroll/salary-processing
4. Intelligence Models (404 fix): GET /api/v1/intelligence/models
5. Company Tenant Isolation & RBAC
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.utils.jwt import create_access_token
from app.core.security import hash_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole, UserAccountStatus
from app.attendance.models.attendance import Attendance


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _create_test_environment(role: UserRole = UserRole.HR_ADMIN):
    """Seed test company, admin user, and return JWT token and IDs."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email = f"test_{user_id.hex[:6]}@example.com"
    phone_num = f"98{user_id.int % 100000000:08d}"
    raw_pwd = "TestPassword@123"

    async with AsyncSessionLocal() as session:
        comp = Company(id=company_id, name=f"Test Company {company_id.hex[:4]}")
        session.add(comp)

        user = User(
            id=user_id,
            company_id=company_id,
            name="Test HR Admin",
            email=email,
            phone=phone_num,
            password_hash=hash_password(raw_pwd),
            role=role,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
            is_verified=True,
        )
        session.add(user)

        employee = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=company_id,
            employee_id=f"EMP-{user_id.hex[:4]}",
            first_name="Test",
            last_name="Employee",
            personal_email=email,
            company_email=email,
            phone=phone_num,
            department="Engineering",
            branch="HQ",
            designation="Developer",
            employment_type="FULL_TIME",
            joining_date=date.today(),
            status="ACTIVE",
            is_active=True,
            is_deleted=False,
        )
        session.add(employee)

        # Seed an attendance record for testing
        attendance = Attendance(
            id=uuid.uuid4(),
            employee_id=emp_id,
            company_id=company_id,
            date=date.today(),
            check_in_time=datetime.now(timezone.utc),
            face_image_url="https://storage.example.com/face.jpg",
            device_info="Chrome Test Agent",
        )
        session.add(attendance)

        await session.commit()

    token = create_access_token(
        user_id=str(user_id),
        email=email,
        role=role.value,
        company_id=str(company_id),
    )

    return {
        "company_id": company_id,
        "user_id": user_id,
        "employee_id": emp_id,
        "email": email,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.mark.asyncio
async def test_face_attendance_company_returns_200(transport):
    """GET /api/v1/attendance/face/company must return HTTP 200 with paginated logs without 500 error."""
    env = await _create_test_environment(role=UserRole.HR_ADMIN)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Standard paginated request
        resp = await client.get(
            "/api/v1/attendance/face/company?page=1&limit=20",
            headers=env["headers"],
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert data["data"]["page"] == 1
        assert data["data"]["limit"] == 20
        assert data["data"]["total"] >= 1
        assert len(data["data"]["items"]) >= 1
        assert data["data"]["items"][0]["employee_name"] == "Test Employee"

        # 2. Filter by branch and department
        resp_filter = await client.get(
            "/api/v1/attendance/face/company?page=1&limit=20&branch=HQ&department=Engineering",
            headers=env["headers"],
        )
        assert resp_filter.status_code == 200
        filter_data = resp_filter.json()
        assert filter_data["success"] is True
        assert filter_data["data"]["total"] >= 1


@pytest.mark.asyncio
async def test_payroll_cycles_v2_returns_200(transport):
    """GET /v2/payroll/cycles and POST /v2/payroll/cycles must return HTTP 200/201 (not 404)."""
    env = await _create_test_environment(role=UserRole.HR_ADMIN)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GET /v2/payroll/cycles
        resp = await client.get("/v2/payroll/cycles", headers=env["headers"])
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "items" in data["data"]

        # POST /v2/payroll/cycles (create test cycle for period 11/2026)
        create_payload = {
            "name": f"Test Payroll Cycle {uuid.uuid4().hex[:4]}",
            "frequency": "MONTHLY",
            "period_month": 11,
            "period_year": 2026,
            "start_date": "2026-11-01",
            "end_date": "2026-11-30",
            "processing_date": "2026-11-28",
            "payment_date": "2026-11-30",
        }
        create_resp = await client.post("/v2/payroll/cycles", json=create_payload, headers=env["headers"])
        assert create_resp.status_code in (200, 201), f"Expected 200/201, got {create_resp.status_code}: {create_resp.text}"
        created_data = create_resp.json()
        assert created_data["success"] is True
        assert created_data["data"]["name"] == create_payload["name"]

        # Duplicate POST /v2/payroll/cycles returns 409 Conflict
        dup_resp = await client.post("/v2/payroll/cycles", json=create_payload, headers=env["headers"])
        assert dup_resp.status_code == 409


@pytest.mark.asyncio
async def test_payroll_salary_processing_v2_returns_200(transport):
    """GET /v2/payroll/salary-processing must return HTTP 200 (not 404)."""
    env = await _create_test_environment(role=UserRole.HR_ADMIN)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GET /v2/payroll/salary-processing
        resp = await client.get(
            "/v2/payroll/salary-processing?page=1&page_size=50",
            headers=env["headers"],
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]

        # Also verify sub-endpoints
        hero_resp = await client.get("/v2/payroll/salary-processing/hero", headers=env["headers"])
        assert hero_resp.status_code == 200
        assert hero_resp.json()["success"] is True


@pytest.mark.asyncio
async def test_intelligence_models_v1_returns_200(transport):
    """GET /api/v1/intelligence/models must return HTTP 200 with list of models (not 404)."""
    env = await _create_test_environment(role=UserRole.EMPLOYEE)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/v1/intelligence/models", headers=env["headers"])
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 5

        # Check default chat model (llama3.1) and embedding model (nomic-embed-text) exist
        model_ids = [m["id"] for m in data["data"]]
        assert "llama3.1" in model_ids
        assert "nomic-embed-text" in model_ids
        assert "mistral" in model_ids


@pytest.mark.asyncio
async def test_multi_tenant_isolation_face_attendance(transport):
    """Company A admin should not see Company B attendance records."""
    env_a = await _create_test_environment(role=UserRole.HR_ADMIN)
    env_b = await _create_test_environment(role=UserRole.HR_ADMIN)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp_a = await client.get("/api/v1/attendance/face/company", headers=env_a["headers"])
        resp_b = await client.get("/api/v1/attendance/face/company", headers=env_b["headers"])

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        data_a = resp_a.json()["data"]
        data_b = resp_b.json()["data"]

        # Verify items belong only to the requesting company
        for item in data_a["items"]:
            assert item["company_id"] == str(env_a["company_id"])
        for item in data_b["items"]:
            assert item["company_id"] == str(env_b["company_id"])


@pytest.mark.asyncio
async def test_unauthorized_requests(transport):
    """Unauthenticated requests must be rejected with 401 or 403 where applicable."""
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Attendance company view requires admin authorization
        resp_att = await client.get("/api/v1/attendance/face/company")
        assert resp_att.status_code in (401, 403)

        # Payroll cycles requires admin or manager authorization
        resp_pay = await client.get("/v2/payroll/cycles")
        assert resp_pay.status_code in (401, 403)
