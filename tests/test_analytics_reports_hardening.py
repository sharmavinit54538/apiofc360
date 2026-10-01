"""Comprehensive tests for Analytics, Reports, and AI Insights hardening."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.database import AsyncSessionLocal
from app.main import app
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.models.employee import Employee
from app.models.exit import EmployeeExit
from app.models.payroll import PayrollRun
from app.models.user import User, UserRole


async def _cleanup_test_data(company_ids: list[uuid.UUID], user_ids: list[uuid.UUID]):
    """Clean up seeded database rows after testing."""
    async with AsyncSessionLocal() as session:
        if company_ids:
            # Delete reports, exits, employees, companies
            await session.execute(
                text("DELETE FROM reports WHERE company_id = ANY(:cids)"),
                {"cids": company_ids},
            )
            await session.execute(
                text("DELETE FROM payroll_runs WHERE company_id = ANY(:cids)"),
                {"cids": company_ids},
            )
            await session.execute(
                text("DELETE FROM employee_exits WHERE company_id = ANY(:cids)"),
                {"cids": company_ids},
            )
            await session.execute(
                text("DELETE FROM employees WHERE company_id = ANY(:cids)"),
                {"cids": company_ids},
            )
            await session.execute(
                text("DELETE FROM users WHERE company_id = ANY(:cids)"),
                {"cids": company_ids},
            )
            await session.execute(
                text("DELETE FROM companies WHERE id = ANY(:cids)"),
                {"cids": company_ids},
            )
        if user_ids:
            await session.execute(
                text("DELETE FROM users WHERE id = ANY(:uids)"),
                {"uids": user_ids},
            )
        await session.commit()


@pytest.mark.asyncio
async def test_analytics_authentication_and_role_authorization():
    """Verify 401 unauthenticated and 403 for unauthorized roles (employee, recruiter, it_admin)."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await _cleanup_test_data([company_id], [user_id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request -> 401
        res = await client.get("/api/v2/reports/analytics/headcount")
        assert res.status_code == 401

        # 2. Authenticated as employee -> 403 Forbidden
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "employee",
        }
        res = await client.get("/api/v2/reports/analytics/headcount")
        assert res.status_code == 403
        assert "not authorized" in res.json().get("detail", "").lower()

        # 3. Authenticated as recruiter -> 403 Forbidden
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "recruiter",
        }
        res = await client.get("/api/v2/reports/analytics/department")
        assert res.status_code == 403

        # 4. Authenticated as it_admin -> 403 Forbidden
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "it_admin",
        }
        res = await client.get("/api/v1/ai-insights/dashboard")
        assert res.status_code == 403

        # 5. Authenticated as hr_admin -> 200 OK
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "hr_admin",
        }
        res = await client.get("/api/v2/reports/analytics/headcount")
        assert res.status_code == 200
        assert res.json()["success"] is True

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_payroll_cost_role_restriction():
    """Verify manager cannot access payroll cost (403), while hr_admin and executive can (200)."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Manager -> 403
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "manager",
        }
        res = await client.get("/api/v2/reports/analytics/payroll-cost")
        assert res.status_code == 403
        assert "not authorized" in res.json().get("detail", "").lower()

        # Export payroll-cost as manager -> 403
        res = await client.get("/api/v2/reports/export?dataset=payroll-cost")
        assert res.status_code == 403

        # Executive -> 200
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "executive",
        }
        res = await client.get("/api/v2/reports/analytics/payroll-cost")
        assert res.status_code == 200

        # HR Admin -> 200
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "hr_admin",
        }
        res = await client.get("/api/v2/reports/analytics/payroll-cost")
        assert res.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_date_range_validation_422():
    """Verify that start_date > end_date returns 422 Unprocessable Entity."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "hr_admin",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_params = "?start_date=2026-12-01&end_date=2026-01-01"
        for endpoint in [
            f"/api/v2/reports/analytics/headcount{bad_params}",
            f"/api/v2/reports/analytics/department{bad_params}",
            f"/api/v2/reports/analytics/tenure{bad_params}",
            f"/api/v2/reports/analytics/turnover{bad_params}",
            f"/api/v2/reports/analytics/payroll-cost{bad_params}",
            f"/api/v2/reports/export{bad_params}&dataset=headcount",
        ]:
            res = await client.get(endpoint)
            assert res.status_code == 422
            msg = res.json().get("detail", "") or res.json().get("message", "")
            assert "start_date" in str(msg).lower()

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_empty_database_honest_results():
    """Verify that when a company has no records, empty lists and has_data=False are returned without sample data."""
    empty_company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(user_id),
        "company_id": str(empty_company_id),
        "role": "hr_admin",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Headcount -> empty list
        res = await client.get("/api/v2/reports/analytics/headcount")
        assert res.status_code == 200
        assert res.json()["data"] == []

        # 2. Department -> empty list
        res = await client.get("/api/v2/reports/analytics/department")
        assert res.status_code == 200
        assert res.json()["data"] == []

        # 3. Tenure -> empty list
        res = await client.get("/api/v2/reports/analytics/tenure")
        assert res.status_code == 200
        assert res.json()["data"] == []

        # 4. Turnover -> empty list
        res = await client.get("/api/v2/reports/analytics/turnover")
        assert res.status_code == 200
        assert res.json()["data"] == []

        # 5. Payroll cost -> empty list
        res = await client.get("/api/v2/reports/analytics/payroll-cost")
        assert res.status_code == 200
        assert res.json()["data"] == []

        # 6. AI Insights Dashboard -> has_data: False, no fake documents or projections
        res = await client.get("/api/v1/ai-insights/dashboard")
        assert res.status_code == 200
        dash = res.json()["data"]
        assert dash["has_data"] is False
        assert dash["kpi"] == []
        assert dash["attrition"] == []
        assert dash["burnout"] == []
        assert dash["documents"] == []
        assert dash["charts"]["headcountForecast"] == []
        assert dash["charts"]["hiringDemand"] == []

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_tenant_isolation_and_scoping():
    """Verify Company A cannot see Company B employees or reports."""
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    emp_a = uuid.uuid4()
    emp_b = uuid.uuid4()

    await _cleanup_test_data([company_a, company_b], [user_a, user_b])

    async with AsyncSessionLocal() as session:
        comp_a = Company(id=company_a, name="Company Alpha", hr_settings={})
        comp_b = Company(id=company_b, name="Company Beta", hr_settings={})
        e_a = Employee(
            id=emp_a,
            user_id=user_a,
            company_id=company_a,
            first_name="Alice",
            last_name="Alpha",
            personal_email="alice@alpha.com",
            department="Engineering",
            joining_date=date(2025, 1, 1),
            basic_salary=80000,
            status="ACTIVE",
        )
        e_b = Employee(
            id=emp_b,
            user_id=user_b,
            company_id=company_b,
            first_name="Bob",
            last_name="Beta",
            personal_email="bob@beta.com",
            department="Marketing",
            joining_date=date(2025, 2, 1),
            basic_salary=60000,
            status="ACTIVE",
        )
        session.add_all([comp_a, comp_b, e_a, e_b])
        await session.commit()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Query as Company A
            app.dependency_overrides[get_current_user_claims] = lambda: {
                "sub": str(user_a),
                "company_id": str(company_a),
                "role": "hr_admin",
            }
            res_a = await client.get("/api/v2/reports/analytics/department")
            assert res_a.status_code == 200
            depts_a = {d["name"]: d["value"] for d in res_a.json()["data"]}
            assert "Engineering" in depts_a
            assert "Marketing" not in depts_a  # Bob's department must not appear!
            assert depts_a["Engineering"] == 1

            # Query as Company B
            app.dependency_overrides[get_current_user_claims] = lambda: {
                "sub": str(user_b),
                "company_id": str(company_b),
                "role": "hr_admin",
            }
            res_b = await client.get("/api/v2/reports/analytics/department")
            assert res_b.status_code == 200
            depts_b = {d["name"]: d["value"] for d in res_b.json()["data"]}
            assert "Marketing" in depts_b
            assert "Engineering" not in depts_b  # Alice's department must not appear!
            assert depts_b["Marketing"] == 1
    finally:
        app.dependency_overrides.clear()
        await _cleanup_test_data([company_a, company_b], [user_a, user_b])


@pytest.mark.asyncio
async def test_manager_hierarchy_scoping():
    """Verify manager sees only reporting hierarchy, while HR Admin sees all company employees."""
    company_id = uuid.uuid4()
    mgr_user_id = uuid.uuid4()
    mgr_emp_id = uuid.uuid4()
    report_user_id = uuid.uuid4()
    report_emp_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    other_emp_id = uuid.uuid4()

    await _cleanup_test_data([company_id], [mgr_user_id, report_user_id, other_user_id])

    async with AsyncSessionLocal() as session:
        comp = Company(id=company_id, name="Hierarchy Test Co", hr_settings={})
        mgr_user = User(
            id=mgr_user_id,
            company_id=company_id,
            name="Manager User",
            email="mgr@test.com",
            phone="9000000001",
            password_hash="hash",
            role=UserRole.MANAGER,
        )
        mgr_emp = Employee(
            id=mgr_emp_id,
            user_id=mgr_user_id,
            company_id=company_id,
            first_name="Manager",
            last_name="Boss",
            personal_email="mgr@test.com",
            department="Engineering",
            joining_date=date(2024, 1, 1),
            status="ACTIVE",
        )
        report_emp = Employee(
            id=report_emp_id,
            user_id=report_user_id,
            company_id=company_id,
            first_name="Direct",
            last_name="Report",
            personal_email="report@test.com",
            department="Engineering",
            joining_date=date(2024, 6, 1),
            reporting_manager_id=mgr_emp_id,  # reports to mgr
            status="ACTIVE",
        )
        other_emp = Employee(
            id=other_emp_id,
            user_id=other_user_id,
            company_id=company_id,
            first_name="Independent",
            last_name="SalesPerson",
            personal_email="sales@test.com",
            department="Sales",  # Not in manager's tree
            joining_date=date(2024, 8, 1),
            reporting_manager_id=None,
            status="ACTIVE",
        )
        session.add_all([comp, mgr_user, mgr_emp, report_emp, other_emp])
        await session.commit()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. As HR Admin: sees both Engineering (2) and Sales (1)
            app.dependency_overrides[get_current_user_claims] = lambda: {
                "sub": str(mgr_user_id),
                "company_id": str(company_id),
                "role": "hr_admin",
            }
            res_admin = await client.get("/api/v2/reports/analytics/department")
            assert res_admin.status_code == 200
            depts_admin = {d["name"]: d["value"] for d in res_admin.json()["data"]}
            assert depts_admin.get("Engineering") == 2
            assert depts_admin.get("Sales") == 1

            # 2. As Manager: sees ONLY their reporting tree (Manager + Direct Report = Engineering: 2, Sales: 0)
            app.dependency_overrides[get_current_user_claims] = lambda: {
                "sub": str(mgr_user_id),
                "company_id": str(company_id),
                "role": "manager",
            }
            res_mgr = await client.get("/api/v2/reports/analytics/department")
            assert res_mgr.status_code == 200
            depts_mgr = {d["name"]: d["value"] for d in res_mgr.json()["data"]}
            assert depts_mgr.get("Engineering") == 2
            assert "Sales" not in depts_mgr  # Other employee is excluded!
    finally:
        app.dependency_overrides.clear()
        await _cleanup_test_data([company_id], [mgr_user_id, report_user_id, other_user_id])


@pytest.mark.asyncio
async def test_csv_export_endpoint():
    """Verify CSV export for headcount, department, and tenure."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "hr_admin",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Headcount CSV
        res = await client.get("/api/v2/reports/export?dataset=headcount")
        assert res.status_code == 200
        assert "text/csv" in res.headers["content-type"]
        assert "Month,Headcount" in res.text

        # Department CSV
        res = await client.get("/api/v2/reports/export?dataset=department")
        assert res.status_code == 200
        assert "Department,Employee Count" in res.text

        # Invalid dataset -> 400
        res = await client.get("/api/v2/reports/export?dataset=unsupported_dataset")
        assert res.status_code == 400

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ai_insights_resilience_and_partial_handling():
    """Verify that AI Insights returns a valid structure with fault tolerance."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    app.dependency_overrides[get_current_user_claims] = lambda: {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "hr_admin",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/ai-insights/dashboard")
        assert res.status_code == 200
        payload = res.json()["data"]
        assert "has_data" in payload
        assert "kpi" in payload
        assert "charts" in payload
        assert "recruitment" in payload
        assert "performance" in payload
        assert "recommendations" in payload
        # Ensure partial flag exists
        assert "partial" in payload

    app.dependency_overrides.clear()
