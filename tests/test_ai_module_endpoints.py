"""Integration tests for granular AI module REST endpoints.

Tests all standardized endpoints for:
1. Workforce Insights:
   - GET /api/v1/workforce-insights/dashboard
   - GET /api/v1/workforce-insights/kpi
   - GET /api/v1/workforce-insights/headcount-trends
   - GET /api/v1/workforce-insights/department-comparison
2. Employee Health:
   - GET /api/v1/employee-health/dashboard
   - GET /api/v1/employee-health/kpi
   - GET /api/v1/employee-health/burnout-trend
   - GET /api/v1/employee-health/overtime
3. Meeting Intelligence:
   - GET /api/v1/meeting-intelligence/dashboard
   - GET /api/v1/meeting-intelligence/kpi
   - GET /api/v1/meeting-intelligence/action-items
   - GET /api/v1/meeting-intelligence/volume

Also verifies that aliased endpoints under /api/v1/ai/* and /api/v1/ai-brain/* remain functional.
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


async def _seed_test_company_and_user(role: UserRole = UserRole.HR_ADMIN):
    """Seed test company, employee, and user returning JWT headers and company_id."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email = f"ai_tester_{user_id.hex[:6]}@example.com"
    phone = f"98{user_id.int % 100000000:08d}"

    async with AsyncSessionLocal() as session:
        comp = Company(id=company_id, name=f"AI Test Enterprise {company_id.hex[:4]}")
        session.add(comp)

        emp = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=company_id,
            employee_id=f"EMP-{emp_id.hex[:4]}",
            first_name="Anita",
            last_name="Desai",
            personal_email=email,
            company_email=email,
            phone=phone,
            department="Engineering",
            designation="Senior AI Engineer",
            joining_date=date(2023, 1, 15),
            status="ACTIVE",
            is_active=True,
        )
        session.add(emp)

        user = User(
            id=user_id,
            company_id=company_id,
            name="Anita Desai",
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


# =============================================================================
# Workforce Insights Tests
# =============================================================================

@pytest.mark.asyncio
async def test_workforce_insights_dashboard(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/workforce-insights/dashboard", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "planned_hires" in data or "plannedHires" in data
        assert "capacity_utilization_pct" in data or "capacityUtilizationPct" in data


@pytest.mark.asyncio
async def test_workforce_insights_kpi(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/workforce-insights/kpi", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "kpis" in data or "workforce_size" in data


@pytest.mark.asyncio
async def test_workforce_insights_headcount_trends(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/workforce-insights/headcount-trends", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "headcount_trends" in data or "headcountTrends" in data


@pytest.mark.asyncio
async def test_workforce_insights_department_comparison(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/workforce-insights/department-comparison", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "department_comparison" in data or "departmentComparison" in data or "departments" in data


# =============================================================================
# Employee Health Tests
# =============================================================================

@pytest.mark.asyncio
async def test_employee_health_dashboard(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/employee-health/dashboard", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "wellbeing_score" in data or "wellbeingScore" in data
        assert "burnout_risk" in data or "burnoutRisk" in data


@pytest.mark.asyncio
async def test_employee_health_kpi(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/employee-health/kpi", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "kpis" in data or "wellbeing_score" in data or "wellbeingScore" in data


@pytest.mark.asyncio
async def test_employee_health_burnout_trend(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/employee-health/burnout-trend", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "burnout_trend" in data or "burnoutTrend" in data


@pytest.mark.asyncio
async def test_employee_health_overtime(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/employee-health/overtime", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "total_ot_hours" in data or "totalOtHours" in data or "team_overtime" in data


# =============================================================================
# Meeting Intelligence Tests
# =============================================================================

@pytest.mark.asyncio
async def test_meeting_intelligence_dashboard(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/meeting-intelligence/dashboard", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "meetings_analyzed" in data or "meetingsAnalyzed" in data
        assert "action_items" in data or "actionItems" in data


@pytest.mark.asyncio
async def test_meeting_intelligence_kpi(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/meeting-intelligence/kpi", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "kpis" in data or "meetings_analyzed" in data or "meetingsAnalyzed" in data


@pytest.mark.asyncio
async def test_meeting_intelligence_action_items(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/meeting-intelligence/action-items", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "action_items" in data or "actionItems" in data or "items" in data


@pytest.mark.asyncio
async def test_meeting_intelligence_volume(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/meeting-intelligence/volume", headers=actor["headers"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data is not None
        assert "weekly_meetings" in data or "weeklyMeetings" in data or "volume" in data


# =============================================================================
# Aliased / Legacy Endpoints Compatibility Tests
# =============================================================================

@pytest.mark.asyncio
async def test_ai_workforce_kpi_alias(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/ai/workforce/kpi", headers=actor["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_ai_employee_health_kpi_alias(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/ai/employee-health/kpi", headers=actor["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_ai_meeting_kpi_alias(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/ai/meeting/kpi", headers=actor["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_ai_brain_workforce_insights_alias(transport):
    actor = await _seed_test_company_and_user()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/ai-brain/workforce-insights", headers=actor["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
