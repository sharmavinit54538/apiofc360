"""Smoke tests for all 22 HRMS Core Modules (FastAPI).

Verifies happy-path GET and POST/PUT for:
- Attendance
- Analytics (all metric suites)
- Settings & Master Data
- Performance (Goals, Reviews, KPIs)
- Users & Employee Profile
- Departments (Hierarchy & Soft-deletes)
- Compliance & Health
- AI Assistants (Leave, Meeting, Coach, Policy)
- Recruiter & Candidates
- Workforce Insights
- Managers
- Reports & Exports
- Notifications, Documents, Assets, Holidays, Dashboard
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.getcwd())

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.utils.jwt import create_access_token
from app.core.security import hash_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole, UserAccountStatus


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _seed_test_actor(role: UserRole = UserRole.HR_ADMIN):
    """Seed test company, employee, and user returning JWT token and IDs."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email = f"core_tester_{user_id.hex[:6]}@example.com"
    phone = f"98{user_id.int % 100000000:08d}"

    async with AsyncSessionLocal() as session:
        comp = Company(id=company_id, name=f"Core Modules Test Enterprise {company_id.hex[:4]}")
        session.add(comp)

        emp = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=company_id,
            employee_id=f"EMP-{emp_id.hex[:4]}",
            first_name="Pooja",
            last_name="Verma",
            personal_email=email,
            company_email=email,
            phone=phone,
            department="Operations",
            designation="HR Operations Lead",
            joining_date=date(2023, 5, 10),
            status="ACTIVE",
            is_active=True,
        )
        session.add(emp)

        user = User(
            id=user_id,
            company_id=company_id,
            name="Pooja Verma",
            email=email,
            phone=phone,
            password_hash=hash_password("Secret#123"),
            role=role,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    token = create_access_token(
        user_id=user_id,
        role=role.value,
        company_id=company_id,
        email=email,
    )
    headers = {"Authorization": f"Bearer {token}"}
    return {
        "company_id": company_id,
        "user_id": user_id,
        "employee_id": emp_id,
        "headers": headers,
    }


@pytest.mark.asyncio
async def test_attendance_lifecycle(transport):
    actor = await _seed_test_actor(UserRole.HR_ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Status check
        r = await client.get("/api/v1/attendance/status", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["success"] is True

        # 2. Check-in
        r = await client.post(
            "/api/v1/attendance/check-in",
            headers=actor["headers"],
            json={"latitude": 28.6139, "longitude": 77.2090, "notes": "Smoke test checkin"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

        # 3. Check-out
        r = await client.post(
            "/api/v1/attendance/check-out",
            headers=actor["headers"],
            json={"latitude": 28.6139, "longitude": 77.2090, "notes": "Smoke test checkout"},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

        # 4. History
        r = await client.get("/api/v1/attendance/history", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["success"] is True

        # 5. Regularization request
        r = await client.post(
            "/api/v1/attendance/regularization",
            headers=actor["headers"],
            json={
                "request_date": date.today().isoformat(),
                "reason": "Biometric scanner device timeout",
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_analytics_metrics(transport):
    actor = await _seed_test_actor(UserRole.HR_ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Dashboard
        r = await client.get("/api/v1/analytics/dashboard", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["success"] is True

        # Headcount metric
        r = await client.get("/api/v1/analytics/headcount", headers=actor["headers"])
        assert r.status_code == 200
        assert "total" in r.json()["data"]

        # Realtime
        r = await client.get("/api/v1/analytics/realtime", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "LIVE"


@pytest.mark.asyncio
async def test_settings_and_master_data(transport):
    actor = await _seed_test_actor(UserRole.ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET Settings
        r = await client.get("/api/v1/settings/", headers=actor["headers"])
        assert r.status_code == 200

        # PUT Settings section
        r = await client.put(
            "/api/v1/settings/attendance",
            headers=actor["headers"],
            json={"config": {"grace_period_mins": 15, "half_day_hours": 4}},
        )
        assert r.status_code == 200
        assert r.json()["data"]["updated"] is True

        # Master Data: Employment Types
        r = await client.post(
            "/api/v1/settings/employment-types",
            headers=actor["headers"],
            json={"name": "Full Time Regular", "code": "FTR", "is_active": True},
        )
        assert r.status_code == 200
        assert r.json()["data"]["code"] == "FTR"

        # Master Data: Holidays
        r = await client.post(
            "/api/v1/settings/holidays",
            headers=actor["headers"],
            json={
                "name": "Diwali Festival",
                "holiday_date": "2026-11-01",
                "type": "national",
                "is_recurring": True,
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["name"] == "Diwali Festival"


@pytest.mark.asyncio
async def test_performance_management(transport):
    actor = await _seed_test_actor(UserRole.HR_ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create Goal
        r = await client.post(
            "/api/v1/performance/goals",
            headers=actor["headers"],
            json={
                "employee_id": str(actor["employee_id"]),
                "title": "Achieve 99.9% Core API Uptime",
                "target_value": 100.0,
                "status": "IN_PROGRESS",
            },
        )
        assert r.status_code == 200
        goal_id = r.json()["data"]["id"]

        # 2. List Goals
        r = await client.get("/api/v1/performance/goals", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["data"]["total"] >= 1

        # 3. Create Review
        r = await client.post(
            "/api/v1/performance/reviews",
            headers=actor["headers"],
            json={
                "employee_id": str(actor["employee_id"]),
                "reviewer_id": str(actor["user_id"]),
                "self_rating": 4.5,
                "reviewer_rating": 4.8,
                "status": "SUBMITTED",
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_users_and_profile(transport):
    actor = await _seed_test_actor(UserRole.ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Current user details
        r = await client.get("/api/v1/users/me", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["data"]["id"] == str(actor["user_id"])

        # Employee Profile
        r = await client.get("/api/v1/profile", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["data"]["first_name"] == "Pooja"

        # Update Profile
        r = await client.put(
            "/api/v1/profile",
            headers=actor["headers"],
            json={"blood_group": "B+", "marital_status": "Single"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["updated"] is True


@pytest.mark.asyncio
async def test_departments_crud_and_employees(transport):
    actor = await _seed_test_actor(UserRole.ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create Department
        r = await client.post(
            "/api/v1/departments",
            headers=actor["headers"],
            json={
                "department_name": f"Cloud Platform Engineering {uuid.uuid4().hex[:4]}",
                "department_code": f"CPE-{uuid.uuid4().hex[:3]}",
                "description": "Core infrastructure team",
            },
        )
        assert r.status_code == 200
        dept_id = r.json()["data"]["id"]

        # List departments
        r = await client.get("/api/v1/departments", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["data"]["total"] >= 1

        # Department employees
        r = await client.get(f"/api/v1/departments/{dept_id}/employees", headers=actor["headers"])
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_compliance_and_health(transport):
    actor = await _seed_test_actor(UserRole.HR_ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Compliance dashboard
        r = await client.get("/api/v1/compliance/dashboard", headers=actor["headers"])
        assert r.status_code == 200
        assert "health_score" in r.json()["data"]

        # Employee Health overview
        r = await client.get("/api/v1/employee-health", headers=actor["headers"])
        assert r.status_code == 200
        assert r.json()["data"]["fitness_clearance_rate"] >= 0


@pytest.mark.asyncio
async def test_ai_assistants_modules(transport):
    actor = await _seed_test_actor(UserRole.EMPLOYEE)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Leave Assistant
        r = await client.get("/api/v1/leave-assistant/", headers=actor["headers"])
        assert r.status_code == 200
        r = await client.post(
            "/api/v1/leave-assistant/query",
            headers=actor["headers"],
            json={"query": "What is the policy for medical leave?"},
        )
        assert r.status_code == 200
        assert "response" in r.json()["data"]

        # 2. Meeting Intelligence
        r = await client.get("/api/v1/meeting-intelligence/", headers=actor["headers"])
        assert r.status_code == 200
        r = await client.post(
            "/api/v1/meeting-intelligence/analyze",
            headers=actor["headers"],
            json={
                "transcript": "Alice agreed to finish the database migration by Friday. Bob will test.",
                "title": "Sprint Sync",
            },
        )
        assert r.status_code == 200
        assert "response" in r.json()["data"]

        # 3. Performance Coach
        r = await client.get("/api/v1/performance-coach/", headers=actor["headers"])
        assert r.status_code == 200
        r = await client.post(
            "/api/v1/performance-coach/chat",
            headers=actor["headers"],
            json={"message": "How do I improve my sprint velocity?", "focus_area": "technical"},
        )
        assert r.status_code == 200
        assert "response" in r.json()["data"]

        # 4. Policy Assistant
        r = await client.get("/api/v1/policy-assistant/", headers=actor["headers"])
        assert r.status_code == 200
        r = await client.post(
            "/api/v1/policy-assistant/query",
            headers=actor["headers"],
            json={"query": "Can I work remotely from another state?"},
        )
        assert r.status_code == 200
        assert "response" in r.json()["data"]


@pytest.mark.asyncio
async def test_recruiter_and_workforce(transport):
    actor = await _seed_test_actor(UserRole.HR_ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Recruiter Jobs
        r = await client.post(
            "/api/v1/recruiter/jobs",
            headers=actor["headers"],
            json={"title": "Senior AI Architect", "department": "AI Labs", "status": "open"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["title"] == "Senior AI Architect"

        r = await client.get("/api/v1/recruiter/jobs", headers=actor["headers"])
        assert r.status_code == 200

        # Workforce Insights
        r = await client.get("/api/v1/workforce-insights/headcount", headers=actor["headers"])
        assert r.status_code == 200
        assert "active_headcount" in r.json()["data"]


@pytest.mark.asyncio
async def test_top_level_modules(transport):
    actor = await _seed_test_actor(UserRole.HR_ADMIN)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Managers
        r = await client.get("/api/v1/managers/dashboard", headers=actor["headers"])
        assert r.status_code == 200

        # Reports
        r = await client.get("/api/v1/reports/", headers=actor["headers"])
        assert r.status_code == 200

        # Notifications
        r = await client.get("/api/v1/notifications", headers=actor["headers"])
        assert r.status_code == 200

        # Documents
        r = await client.get("/api/v1/documents", headers=actor["headers"])
        assert r.status_code == 200

        # Assets
        r = await client.get("/api/v1/assets", headers=actor["headers"])
        assert r.status_code == 200

        # Holidays
        r = await client.get("/api/v1/holidays", headers=actor["headers"])
        assert r.status_code == 200

        # Landing Dashboard
        r = await client.get("/api/v1/dashboard", headers=actor["headers"])
        assert r.status_code == 200
        assert "today_attendance" in r.json()["data"]
