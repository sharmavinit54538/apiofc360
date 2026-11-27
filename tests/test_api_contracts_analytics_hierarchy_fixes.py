"""Isolated PostgreSQL 18 regression tests for Hierarchy, Super-Admin RBAC, Attendance Analytics, Designations, Shifts, Expenses, and Read-Only Onboarding GET."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.attendance.models.attendance import Attendance
from app.core.config import settings
from app.core.field_encryption import ENCRYPTED_VALUE_PREFIX
from app.core.security import create_access_token, hash_password
from app.db.base import Base, tenant_id_ctx
from app.db.database import get_db_session
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models.company import Company
from app.models.core_modules import Holiday
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.payroll import ReimbursementClaim
from app.models.shift import Shift
from app.models.user import OFFICIAL_SUPER_ADMIN_EMAIL, User, UserRole

pytestmark = pytest.mark.asyncio

PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
KEY_NEW = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
UNCONFIGURED_CIPHERTEXT = f"{ENCRYPTED_VALUE_PREFIX}0eb07e19bb3a:deadbeef:deadbeef"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _pg_ctl(pgdata: Path, args: list[str], *, check: bool = True) -> None:
    subprocess.run(
        [str(PG_BIN / "pg_ctl.exe"), "-D", str(pgdata), *args],
        check=check,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest_asyncio.fixture(scope="module")
async def pg_cluster_info():
    if not (PG_BIN / "initdb.exe").exists():
        pytest.skip("PostgreSQL 18 binaries not available for isolated PG test cluster")

    port = _free_port()
    tmp_dir = Path(tempfile.mkdtemp(prefix="pg_contracts_test_"))
    pgdata = tmp_dir / "pgdata"
    logfile = tmp_dir / "pg.log"
    db_name = "ofc360_contracts_test"

    subprocess.run(
        [str(PG_BIN / "initdb.exe"), "-D", str(pgdata), "-U", "postgres", "-A", "trust", "--encoding=UTF8"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _pg_ctl(pgdata, ["-l", str(logfile), "-o", f"-p {port} -F", "start"], check=True)
    try:
        subprocess.run(
            [str(PG_BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", db_name],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{port}/{db_name}"
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()
        yield {"url": url, "port": port}
    finally:
        _pg_ctl(pgdata, ["stop", "-m", "immediate"], check=False)
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def pg_ctx(pg_cluster_info, monkeypatch):
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_NEW))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_NEW)

    eng = create_async_engine(pg_cluster_info["url"], poolclass=NullPool)
    sf = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db():
        async with sf() as s:
            try:
                yield s
            finally:
                tenant_id_ctx.set(None)

    fastapi_app.dependency_overrides[get_db_session] = _override_get_db
    try:
        async with sf() as s:
            yield s, eng
    finally:
        fastapi_app.dependency_overrides.pop(get_db_session, None)
        tenant_id_ctx.set(None)
        await eng.dispose()


async def _make_user(
    session: AsyncSession,
    *,
    company_id: uuid.UUID | None,
    role: UserRole,
    name: str,
    email: str | None = None,
    is_active: bool = True,
    is_deleted: bool = False,
    account_status: str = "ACTIVE",
) -> User:
    u = User(
        id=uuid.uuid4(),
        company_id=company_id,
        name=name,
        email=email or f"{name.lower().replace(' ', '.')}.{uuid.uuid4().hex[:6]}@example.test",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        password_hash=hash_password("StrongPass!123"),
        is_active=is_active,
        is_verified=True,
        is_deleted=is_deleted,
        account_status=account_status,
        role=role,
    )
    session.add(u)
    await session.flush()
    return u


def _auth_headers(user: User) -> dict[str, str]:
    tok = create_access_token(
        subject=str(user.id),
        claims={
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "company_id": str(user.company_id) if user.company_id else None,
            "email": user.email,
        },
    )
    return {"Authorization": f"Bearer {tok}"}


async def test_employees_hierarchy_and_super_admin_account_state_guards(pg_ctx):
    """GET /api/v1/employees/hierarchy returns 200 tree (no 422); _get_is_super_admin enforces ACTIVE user."""
    session, _ = pg_ctx
    cid_a = uuid.uuid4()
    cid_b = uuid.uuid4()
    session.add_all([Company(id=cid_a, name="Tree Co A"), Company(id=cid_b, name="Tree Co B")])
    await session.flush()

    hr_a = await _make_user(session, company_id=cid_a, role=UserRole.HR_ADMIN, name="HR A")
    emp_b_user = await _make_user(session, company_id=cid_b, role=UserRole.HR_ADMIN, name="HR B")
    super_admin = await _make_user(
        session,
        company_id=None,
        role=UserRole.SUPER_ADMIN,
        name="Platform Owner",
        email=OFFICIAL_SUPER_ADMIN_EMAIL,
        is_active=True,
        account_status="ACTIVE",
    )

    ceo = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        employee_id=f"CEO-{uuid.uuid4().hex[:5]}",
        first_name="Aarav",
        last_name="Mehta",
        personal_email=f"ceo.{uuid.uuid4().hex[:6]}@t.co",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Leadership",
        designation="CEO",
        role="executive",
        status="ACTIVE",
        joining_date=date(2024, 1, 1),
    )
    lead = Employee(
        id=uuid.uuid4(),
        company_id=cid_a,
        employee_id=f"EMP-{uuid.uuid4().hex[:5]}",
        first_name="Neha",
        last_name="Rao",
        personal_email=f"neha.{uuid.uuid4().hex[:6]}@t.co",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Engineering",
        designation="Engineering Lead",
        manager_id=ceo.id,
        role="manager",
        status="ACTIVE",
        joining_date=date(2024, 6, 1),
    )
    other_co_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid_b,
        employee_id=f"EXT-{uuid.uuid4().hex[:5]}",
        first_name="Other",
        last_name="Tenant",
        personal_email=f"other.{uuid.uuid4().hex[:6]}@t.co",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Sales",
        designation="VP",
        role="executive",
        status="ACTIVE",
        joining_date=date(2024, 2, 1),
    )
    session.add_all([ceo, lead, other_co_emp])
    await session.commit()

    # Corrupt encrypted PII to prove hierarchy routes never touch unreadable legacy keys
    await session.execute(
        text("UPDATE employees SET pan_number = :c, aadhaar_number = :c WHERE company_id = :cid"),
        {"c": UNCONFIGURED_CIPHERTEXT, "cid": cid_a},
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        r_emp_hier = await client.get("/api/v1/employees/hierarchy", headers=_auth_headers(hr_a))
        assert r_emp_hier.status_code == 200, r_emp_hier.text
        tree = r_emp_hier.json()["data"]
        assert len(tree) == 1
        assert tree[0]["id"] == str(ceo.id)
        assert [c["id"] for c in tree[0]["children"]] == [str(lead.id)]

        r_emp_rep = await client.get(f"/api/v1/employees/{lead.id}/reporting", headers=_auth_headers(hr_a))
        assert r_emp_rep.status_code == 200, r_emp_rep.text
        assert r_emp_rep.json()["data"]["manager"]["id"] == str(ceo.id)

        r_rep = await client.get(f"/api/v1/employees/{lead.id}/reporting", headers=_auth_headers(hr_a))
        assert r_rep.status_code == 200, r_rep.text
        assert r_rep.json()["data"]["manager"]["id"] == str(ceo.id)

        # Tenant isolation: Tenant B does not see Tenant A nodes
        r_b_hier = await client.get("/api/v1/employees/hierarchy", headers=_auth_headers(emp_b_user))
        assert r_b_hier.status_code == 200
        assert [n["id"] for n in r_b_hier.json()["data"]] == [str(other_co_emp.id)]

        # Active verified official Super Admin can inspect Tenant A hierarchy details
        r_sa = await client.get(f"/api/v1/hierarchy/{lead.id}", headers=_auth_headers(super_admin))
        assert r_sa.status_code == 200, r_sa.text
        assert r_sa.json()["data"]["manager"]["id"] == str(ceo.id)

        # Inactive / suspended / deleted Super Admin must NEVER receive elevated privileges (fails closed at auth/RBAC)
        super_admin.is_active = False
        super_admin.account_status = "SUSPENDED"
        await session.commit()
        r_sa_suspended = await client.get(f"/api/v1/hierarchy/{lead.id}", headers=_auth_headers(super_admin))
        assert r_sa_suspended.status_code in (401, 403), r_sa_suspended.text


async def test_attendance_analytics_endpoints_and_filters_no_sql_errors(pg_ctx):
    """Attendance distribution/rate-kpi/rate/weekly/trends & records handle booleans, nulls, leaves, holidays, and empty sets cleanly."""
    session, _ = pg_ctx
    cid_empty = uuid.uuid4()
    cid = uuid.uuid4()
    session.add_all([Company(id=cid_empty, name="Empty Attendance Co"), Company(id=cid, name="Active Attendance Co")])
    await session.flush()

    hr_empty = await _make_user(session, company_id=cid_empty, role=UserRole.HR_ADMIN, name="HR Empty")
    hr = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="HR Att")

    # 1. Empty company dataset: must return 200 with zero denominators safely
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        for path in (
            "/api/v1/attendance/analytics/distribution",
            "/api/v1/attendance/analytics/rate-kpi",
            "/api/v1/attendance/analytics/rate",
            "/api/v1/attendance/analytics/weekly",
            "/api/v1/attendance/analytics/trends",
        ):
            r = await client.get(path, headers=_auth_headers(hr_empty))
            assert r.status_code == 200, f"{path} failed on empty data: {r.text}"

    # 2. Seed rich Monday..Friday working window ending in the past (fixed completed Mon-Fri week)
    mon = date(2026, 11, 2)
    fri = date(2026, 11, 6)
    wed_holiday = date(2026, 11, 4)

    emp1 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=f"AT1-{uuid.uuid4().hex[:5]}",
        first_name="Priya",
        last_name="Nair",
        personal_email=f"priya.{uuid.uuid4().hex[:6]}@t.co",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Engineering",
        designation="SWE",
        shift="General",
        work_location="Bengaluru",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 1, 1),
    )
    emp2 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=f"AT2-{uuid.uuid4().hex[:5]}",
        first_name="Vikram",
        last_name="Joshi",
        personal_email=f"vikram.{uuid.uuid4().hex[:6]}@t.co",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Sales",
        designation="AE",
        shift="General",
        work_location="Mumbai",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 1, 1),
    )
    session.add_all([emp1, emp2])
    await session.flush()

    session.add(
        Holiday(
            id=uuid.uuid4(),
            company_id=cid,
            name="Midweek Foundation Day",
            holiday_date=wed_holiday,
            type="company",
            is_recurring=False,
        )
    )
    session.add(
        LeaveRequest(
            id=uuid.uuid4(),
            employee_id=emp2.id,
            leave_type="Casual Leave",
            start_date=date(2026, 11, 3),
            end_date=date(2026, 11, 3),
            total_days=Decimal("1.0"),
            reason="Personal",
            status="APPROVED",
        )
    )
    # Monday: emp1 present on-time (9.5h -> 1.5h OT), emp2 late; Tuesday: emp1 WFH, emp2 on approved leave; previous week Monday: emp1 present
    session.add_all([
        Attendance(
            id=uuid.uuid4(),
            company_id=cid,
            employee_id=emp1.id,
            date=mon,
            check_in_time=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc),
            check_out_time=datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc),
            status="Present",
            is_late=False,
            working_hours=9.5,
        ),
        Attendance(
            id=uuid.uuid4(),
            company_id=cid,
            employee_id=emp2.id,
            date=mon,
            check_in_time=datetime(2026, 11, 2, 10, 5, tzinfo=timezone.utc),
            check_out_time=None,  # test NULL check_out_time and NULL working_hours edge case!
            status="Late",
            is_late=True,
            working_hours=None,
        ),
        Attendance(
            id=uuid.uuid4(),
            company_id=cid,
            employee_id=emp1.id,
            date=date(2026, 11, 3),
            check_in_time=datetime(2026, 11, 3, 9, 5, tzinfo=timezone.utc),
            check_out_time=datetime(2026, 11, 3, 17, 5, tzinfo=timezone.utc),
            status="WFH",
            is_late=False,
            working_hours=8.0,
            punch_verified_by="REMOTE",
        ),
        Attendance(
            id=uuid.uuid4(),
            company_id=cid,
            employee_id=emp1.id,
            date=date(2026, 10, 26),
            check_in_time=datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc),
            status="Present",
            is_late=False,
            working_hours=8.0,
        ),
    ])
    await session.commit()

    params = {"viewMode": "week", "startDate": mon.isoformat(), "endDate": fri.isoformat()}
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        r_dist = await client.get("/api/v1/attendance/analytics/distribution", params=params, headers=_auth_headers(hr))
        assert r_dist.status_code == 200, r_dist.text
        dist = r_dist.json()["data"]
        assert dist["present"] == 2  # emp1 Mon + emp1 Tue WFH (on-time present)
        assert dist["late"] == 1     # emp2 Mon
        assert dist["on_leave"] == 1  # emp2 Tue approved leave
        assert dist["wfh"] == 1
        assert dist["total"] == dist["present"] + dist["late"] + dist["absent"] + dist["on_leave"]

        r_kpi = await client.get("/api/v1/attendance/analytics/rate-kpi", params=params, headers=_auth_headers(hr))
        assert r_kpi.status_code == 200, r_kpi.text
        kpi = r_kpi.json()["data"]
        assert kpi["present_count"] == 3
        assert kpi["on_leave_count"] == 1
        # Wednesday was a company holiday -> only 4 countable days * 2 employees = 8 expected!
        assert kpi["total_count"] == 8
        assert kpi["current_rate"] == 37.5
        assert kpi["previous_rate"] is not None
        assert kpi["trend"] == "up"

        # Department filter via camelCase parameter
        r_eng = await client.get(
            "/api/v1/attendance/analytics/distribution",
            params={**params, "departmentId": "Engineering"},
            headers=_auth_headers(hr),
        )
        assert r_eng.status_code == 200
        assert r_eng.json()["data"]["present"] == 2
        assert r_eng.json()["data"]["late"] == 0

        r_weekly = await client.get("/api/v1/attendance/analytics/weekly", params=params, headers=_auth_headers(hr))
        assert r_weekly.status_code == 200
        wk = r_weekly.json()["data"]
        assert len(wk["weekly"]) == 7
        assert wk["weekly"][0]["overtime_hours"] == 1.5  # Monday OT from 9.5h
        assert wk["data"] == wk["weekly"]

        r_trends = await client.get("/api/v1/attendance/analytics/trends", params=params, headers=_auth_headers(hr))
        assert r_trends.status_code == 200
        tr = r_trends.json()["data"]
        assert len(tr["trends"]) == 5
        assert tr["data"] == tr["trends"]

        # Employee filter on /attendance/records by both UUID and code
        r_rec = await client.get(
            f"/api/v1/attendance/records?employee_id={emp1.id}",
            headers=_auth_headers(hr),
        )
        assert r_rec.status_code == 200
        rec_data = r_rec.json()["data"]
        assert rec_data["total"] == 3
        assert rec_data["present_days"] == 3
        assert rec_data["late_days"] == 0


async def test_designations_shifts_expenses_and_readonly_onboarding_get(pg_ctx):
    """Canonical /designations, /shifts, /expenses return 200 and GET admin onboarding performs zero DB writes."""
    session, eng = pg_ctx
    cid = uuid.uuid4()
    other_cid = uuid.uuid4()
    session.add_all([Company(id=cid, name="Master Ops Co"), Company(id=other_cid, name="Other Ops Co")])
    await session.flush()

    hr = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="HR Master")
    hr_other = await _make_user(session, company_id=other_cid, role=UserRole.HR_ADMIN, name="Other HR")
    emp_user = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Emp Master")

    emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_user.id,
        employee_id=f"MAS-{uuid.uuid4().hex[:5]}",
        first_name="Sonal",
        last_name="Verma",
        personal_email=f"sonal.{uuid.uuid4().hex[:6]}@t.co",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Product",
        designation="Staff Product Manager",
        shift="Day Core",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 1, 1),
    )
    session.add(emp)
    await session.flush()

    shift = Shift(
        id=uuid.uuid4(),
        company_id=cid,
        code="DAY_CORE",
        name="Day Core",
        start_time=time(9, 30),
        end_time=time(18, 30),
        is_overnight=False,
        duration_minutes=540,
        grace_period_minutes=15,
        break_duration_minutes=60,
        work_hours=8.0,
        is_night_shift=False,
        is_active=True,
        description="Standard 9:30 AM shift",
    )
    claim = ReimbursementClaim(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp.id,
        category="travel",
        amount=Decimal("2450.50"),
        currency="INR",
        claim_date=date(2026, 11, 5),
        description="Client onsite cab",
        merchant="Uber",
        status="SUBMITTED",
        payout_mode="STANDALONE",
    )
    session.add_all([shift, claim])
    await session.commit()

    sql_statements: list[str] = []

    def _capture_sql(conn, cursor, stmt, params, ctx, em):
        sql_statements.append(" ".join(stmt.split()).upper())

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        # 1. Designations canonical + settings compatibility
        r_create_des = await client.post(
            "/api/v1/designations",
            json={"name": "Staff Product Manager", "description": "Senior IC"},
            headers=_auth_headers(hr),
        )
        assert r_create_des.status_code == 201, r_create_des.text
        r_des_list = await client.get("/api/v1/designations?limit=100&search=Product", headers=_auth_headers(hr))
        assert r_des_list.status_code == 200, r_des_list.text
        des_payload = r_des_list.json()["data"]
        assert des_payload["total"] >= 1
        assert any(it["name"] == "Staff Product Manager" for it in des_payload["items"])

        # 2. Shifts canonical /api/v1/shifts & /api/v1/attendance/shifts
        for path in ("/api/v1/shifts?limit=100", "/api/v1/attendance/shifts?limit=100"):
            r_sh = await client.get(path, headers=_auth_headers(hr))
            assert r_sh.status_code == 200, f"{path}: {r_sh.text}"
            sh_items = r_sh.json()["data"]["items"]
            assert len(sh_items) == 1
            assert sh_items[0]["shift_code"] == "DAY_CORE"
            assert sh_items[0]["break_duration_minutes"] == 60
            assert sh_items[0]["grace_period_minutes"] == 15
            assert sh_items[0]["working_days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
            assert sh_items[0]["employee_count"] == 1

        # 3. Expenses /api/v1/expenses filtered by employee_id + search + tenant isolation
        r_exp = await client.get(f"/api/v1/expenses?employee_id={emp.id}&search=Client&limit=30", headers=_auth_headers(hr))
        assert r_exp.status_code == 200, r_exp.text
        exp_items = r_exp.json()["data"]["items"]
        assert len(exp_items) == 1
        assert exp_items[0]["employee"]["name"] == "Sonal Verma"
        r_exp_other = await client.get(f"/api/v1/expenses?employee_id={emp.id}", headers=_auth_headers(hr_other))
        assert r_exp_other.status_code == 200
        assert r_exp_other.json()["data"]["items"] == []

        # 4. GET /api/v1/admin/employee-onboarding/{emp.id} MUST perform ZERO INSERT/UPDATE writes even with 0 rows!
        # Warm auth first so we inspect onboarding query SQL cleanly
        await client.get(f"/api/v1/employees/{emp.id}", headers=_auth_headers(hr))
        sql_statements.clear()
        event.listen(eng.sync_engine, "before_cursor_execute", _capture_sql)
        try:
            r_ob = await client.get(f"/api/v1/admin/employee-onboarding/{emp.id}", headers=_auth_headers(hr))
        finally:
            event.remove(eng.sync_engine, "before_cursor_execute", _capture_sql)

        assert r_ob.status_code == 200, r_ob.text
        assert r_ob.json()["data"]["status"]["completion_percentage"] == 0.0
        assert len(r_ob.json()["data"]["status"]["steps_completed"]) == 10
        write_sql = [s for s in sql_statements if s.startswith(("INSERT", "UPDATE", "DELETE"))]
        assert write_sql == [], f"GET onboarding unexpectedly mutated DB: {write_sql}"
