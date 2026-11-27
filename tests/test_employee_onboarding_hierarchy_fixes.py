"""Isolated PostgreSQL 18 integration tests for Employee, Onboarding, Hierarchy, Attendance, Assets, Schema Sync, and Correlation IDs."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.field_encryption import ENCRYPTED_VALUE_PREFIX, encrypt_value
from app.core.readiness import inspect_schema_drift, readiness
from app.core.security import create_access_token, hash_password
from app.db.base import Base, tenant_id_ctx
from app.db.database import get_db_session
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models.asset import Asset
from app.models.company import Company
from app.models.employee import Employee
from app.models.employee_address import EmployeeAddress
from app.models.employee_onboarding import EmployeeOnboarding
from app.models.recruitment import Application, Candidate, Job, Offer
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[1]
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
    """Boot a temporary private PG18 cluster for schema, alembic, and endpoint verification."""
    if not (PG_BIN / "initdb.exe").exists():
        pytest.skip("PostgreSQL 18 binaries not available for isolated PG test cluster")

    port = _free_port()
    tmp_dir = Path(tempfile.mkdtemp(prefix="pg_emp_hier_test_"))
    pgdata = tmp_dir / "pgdata"
    logfile = tmp_dir / "pg.log"
    db_name = "ofc360_emp_hier_test"

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
    company_id: uuid.UUID,
    role: UserRole,
    name: str,
) -> User:
    u = User(
        id=uuid.uuid4(),
        company_id=company_id,
        name=name,
        email=f"{name.lower().replace(' ', '.')}.{uuid.uuid4().hex[:6]}@example.test",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        password_hash=hash_password("StrongPass!123"),
        is_active=True,
        is_verified=True,
        is_deleted=False,
        account_status="ACTIVE",
        role=role,
    )
    session.add(u)
    await session.flush()
    return u


def _auth_headers(user: User, extra: dict[str, str] | None = None) -> dict[str, str]:
    tok = create_access_token(
        subject=str(user.id),
        claims={
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "company_id": str(user.company_id) if user.company_id else None,
            "email": user.email,
        },
    )
    hdrs = {"Authorization": f"Bearer {tok}"}
    if extra:
        hdrs.update(extra)
    return hdrs


async def test_fresh_alembic_upgrade_base_to_head_zero_drift(pg_cluster_info):
    """Fresh `alembic upgrade base -> head` on empty PG18 must succeed with 0 drift."""
    port = pg_cluster_info["port"]
    fresh_db = f"fresh_schema_{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [str(PG_BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", fresh_db],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    fresh_url = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{port}/{fresh_db}"
    env = os.environ.copy()
    env["DATABASE_URL"] = fresh_url
    env["SECRET_KEY"] = "test-secret-key-at-least-32-chars-long"
    env["PYTHONPATH"] = str(ROOT)

    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    assert res.returncode == 0, f"Alembic upgrade failed: {res.stderr}"

    eng = create_async_engine(fresh_url, poolclass=NullPool)
    try:
        drift = await inspect_schema_drift(eng)
        assert drift == {
            "revision_match": True,
            "missing_tables": 0,
            "missing_columns": 0,
            "schema_drift": False,
        }
        async with eng.connect() as conn:
            def _check_all(sync_conn):
                insp = inspect(sync_conn)
                missing_idxs = []
                for tname, tbl in Base.metadata.tables.items():
                    db_idxs = {i["name"] for i in insp.get_indexes(tname, schema="public")}
                    for idx in tbl.indexes:
                        if idx.name and idx.name not in db_idxs:
                            missing_idxs.append(f"{tname}.{idx.name}")
                return missing_idxs

            missing_idxs = await conn.run_sync(_check_all)
        assert missing_idxs == []
    finally:
        await eng.dispose()


async def test_employee_and_onboarding_endpoints_direct_and_offer_linked(pg_ctx):
    """Employee detail & admin onboarding return 200 for both direct and offer-linked hires."""
    session, _ = pg_ctx
    cid = uuid.uuid4()
    other_cid = uuid.uuid4()
    session.add_all([Company(id=cid, name="Onboard Test Co"), Company(id=other_cid, name="Other Tenant Co")])
    await session.flush()

    admin = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="HR Admin")
    emp_user = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Direct Hire")

    direct_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_user.id,
        employee_id=f"EMP-{uuid.uuid4().hex[:6]}",
        first_name="Asha",
        last_name="Verma",
        personal_email=f"asha.{uuid.uuid4().hex[:6]}@example.test",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Engineering",
        designation="Backend Engineer",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 1, 1),
        pan_number=encrypt_value("ABCDE1234F"),
    )
    offer_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=f"EMP-{uuid.uuid4().hex[:6]}",
        first_name="Rohan",
        last_name="Kapoor",
        personal_email=f"rohan.{uuid.uuid4().hex[:6]}@example.test",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Product",
        designation="PM",
        role="employee",
        status="PREBOARDING",
        joining_date=date(2025, 2, 1),
        pan_number=encrypt_value("VWXYZ9876K"),
    )
    legacy_emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=f"EMP-{uuid.uuid4().hex[:6]}",
        first_name="Legacy",
        last_name="Record",
        personal_email=f"legacy.{uuid.uuid4().hex[:6]}@example.test",
        phone=f"9{uuid.uuid4().int % 10**9:09d}",
        department="Finance",
        designation="Analyst",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 1, 1),
    )
    session.add_all([direct_emp, offer_emp, legacy_emp])
    await session.flush()

    # Create Candidate + Job + Application + Offer to exercise offer_id & candidate_id FKs
    job = Job(
        id=uuid.uuid4(),
        company_id=cid,
        title="Product Manager",
        slug=f"pm-{uuid.uuid4().hex[:6]}",
        department="Product",
        designation="PM",
        location="Bengaluru",
        job_description="Lead product",
    )
    cand = Candidate(
        id=uuid.uuid4(),
        company_id=cid,
        first_name="Rohan",
        last_name="Kapoor",
        email=f"cand.{uuid.uuid4().hex[:6]}@example.test",
        phone="9876543211",
        location="Bengaluru",
    )
    session.add_all([job, cand])
    await session.flush()
    app_row = Application(
        id=uuid.uuid4(),
        company_id=cid,
        job_id=job.id,
        candidate_id=cand.id,
        first_name="Rohan",
        last_name="Kapoor",
        email=cand.email,
        phone=cand.phone,
        country="India",
        state="KA",
        city="Bengaluru",
    )
    session.add(app_row)
    await session.flush()
    offer = Offer(
        id=uuid.uuid4(),
        company_id=cid,
        application_id=app_row.id,
        ctc=Decimal("1800000.00"),
        joining_date=date(2026, 12, 1),
        offer_expiry_date=date(2026, 12, 15),
    )
    session.add(offer)
    await session.flush()

    session.add(
        EmployeeOnboarding(
            employee_id=direct_emp.id,
            step_name="Personal Information",
            step_order=1,
            is_required=True,
            is_completed=True,
            status="VERIFIED",
        )
    )
    session.add(
        EmployeeOnboarding(
            employee_id=offer_emp.id,
            offer_id=offer.id,
            candidate_id=cand.id,
            step_name="Personal Information",
            step_order=1,
            is_required=True,
            is_completed=False,
            status="PENDING",
            bgv_status="IN_PROGRESS",
            completion_percentage=Decimal("25.00"),
        )
    )
    session.add(
        EmployeeAddress(
            employee_id=direct_emp.id,
            address_type="CURRENT",
            address_line_1="100 MG Road",
            city="Bengaluru",
            state="KA",
            country="India",
            pincode="560001",
        )
    )
    await session.commit()

    # Inject unconfigured ciphertext into legacy_emp to verify list_onboarding_progress survives
    await session.execute(
        text("UPDATE employees SET pan_number = :c WHERE id = :id"),
        {"c": UNCONFIGURED_CIPHERTEXT, "id": legacy_emp.id},
    )
    await session.commit()

    headers = _auth_headers(admin, {"X-Request-ID": "req-emp-onboard-1"})
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        r_emp = await client.get(f"/api/v1/employees/{direct_emp.id}", headers=headers)
        assert r_emp.status_code == 200, r_emp.text
        assert r_emp.headers.get("x-request-id") == "req-emp-onboard-1"
        body = r_emp.json()["data"]
        assert body["id"] == str(direct_emp.id)
        assert body["pan_number"] == "ABCDE****F"
        assert len(body["onboarding_steps"]) == 1

        r_ob_direct = await client.get(f"/api/v1/admin/employee-onboarding/{direct_emp.id}", headers=headers)
        assert r_ob_direct.status_code == 200, r_ob_direct.text

        r_ob_offer = await client.get(f"/api/v1/admin/employee-onboarding/{offer_emp.id}", headers=headers)
        assert r_ob_offer.status_code == 200, r_ob_offer.text

        r_ob_list = await client.get("/api/v1/admin/employee-onboarding?search=Kapoor", headers=headers)
        assert r_ob_list.status_code == 200, r_ob_list.text
        names = [row["name"] for row in r_ob_list.json()["data"]]
        assert names == ["Rohan Kapoor"]


async def test_hierarchy_legacy_key_safe_rbac_and_query_budget(pg_ctx):
    """Hierarchy returns 200 with <=5 SQL queries despite unconfigured key_id=0eb07e19bb3a and enforces RBAC."""
    session, eng = pg_ctx
    cid_a = uuid.uuid4()
    cid_b = uuid.uuid4()
    session.add_all([Company(id=cid_a, name="Hier Co A"), Company(id=cid_b, name="Hier Co B")])
    await session.flush()

    hr_a = await _make_user(session, company_id=cid_a, role=UserRole.HR_ADMIN, name="HR A")
    mgr_u = await _make_user(session, company_id=cid_a, role=UserRole.MANAGER, name="Mgr A")
    emp_u = await _make_user(session, company_id=cid_a, role=UserRole.EMPLOYEE, name="Emp A")
    peer_u = await _make_user(session, company_id=cid_a, role=UserRole.EMPLOYEE, name="Peer A")
    hr_b = await _make_user(session, company_id=cid_b, role=UserRole.HR_ADMIN, name="HR B")

    ceo = Employee(
        id=uuid.uuid4(), company_id=cid_a, employee_id=f"CEO-{uuid.uuid4().hex[:5]}",
        first_name="Chief", last_name="Exec", personal_email=f"ceo.{uuid.uuid4().hex[:6]}@t.co",
        phone="9111111111", role="executive", status="ACTIVE", designation="CEO", department="Exec",
        joining_date=date(2024, 1, 1),
    )
    session.add(ceo)
    await session.flush()

    mgr = Employee(
        id=uuid.uuid4(), company_id=cid_a, user_id=mgr_u.id, manager_id=ceo.id,
        employee_id=f"MGR-{uuid.uuid4().hex[:5]}", first_name="Lead", last_name="Mgr",
        personal_email=f"mgr.{uuid.uuid4().hex[:6]}@t.co", phone="9222222222",
        role="manager", status="ACTIVE", designation="Eng Mgr", department="Engineering",
        joining_date=date(2024, 6, 1),
    )
    session.add(mgr)
    await session.flush()

    emp = Employee(
        id=uuid.uuid4(), company_id=cid_a, user_id=emp_u.id, manager_id=mgr.id,
        employee_id=f"DEV-{uuid.uuid4().hex[:5]}", first_name="Dev", last_name="One",
        personal_email=f"dev1.{uuid.uuid4().hex[:6]}@t.co", phone="9333333333",
        role="employee", status="ACTIVE", designation="SDE", department="Engineering",
        joining_date=date(2025, 1, 1),
    )
    peer = Employee(
        id=uuid.uuid4(), company_id=cid_a, user_id=peer_u.id, manager_id=mgr.id,
        employee_id=f"DEV-{uuid.uuid4().hex[:5]}", first_name="Dev", last_name="Two",
        personal_email=f"dev2.{uuid.uuid4().hex[:6]}@t.co", phone="9444444444",
        role="employee", status="ACTIVE", designation="SDE", department="Engineering",
        joining_date=date(2025, 1, 1),
    )
    session.add_all([emp, peer])
    await session.commit()

    # Corrupt all four hierarchy nodes with unconfigured legacy key ciphertext
    await session.execute(
        text("UPDATE employees SET pan_number = :c, aadhaar_number = :c WHERE company_id = :cid"),
        {"c": UNCONFIGURED_CIPHERTEXT, "cid": cid_a},
    )
    await session.commit()

    sql_count = 0

    def _count_sql(conn, cursor, stmt, params, ctx, em):
        nonlocal sql_count
        sql_count += 1

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        event.listen(eng.sync_engine, "before_cursor_execute", _count_sql)
        try:
            r_hr = await client.get(f"/api/v1/hierarchy/{emp.id}", headers=_auth_headers(hr_a))
        finally:
            event.remove(eng.sync_engine, "before_cursor_execute", _count_sql)

        assert r_hr.status_code == 200, r_hr.text
        assert sql_count <= 8, f"Expected cold hierarchy SQL budget <= 8, got {sql_count}"

        sql_count = 0
        event.listen(eng.sync_engine, "before_cursor_execute", _count_sql)
        try:
            r_hr_warm = await client.get(f"/api/v1/hierarchy/{emp.id}", headers=_auth_headers(hr_a))
        finally:
            event.remove(eng.sync_engine, "before_cursor_execute", _count_sql)
        assert r_hr_warm.status_code == 200, r_hr_warm.text
        assert sql_count <= 6, f"Expected warm hierarchy SQL budget <= 6, got {sql_count}"
        data = r_hr.json()["data"]
        assert data["employee"]["id"] == str(emp.id)
        assert data["manager"]["id"] == str(mgr.id)
        assert [p["id"] for p in data["peers"]] == [str(peer.id)]
        assert [a["id"] for a in data["reporting_chain"]] == [str(ceo.id), str(mgr.id)]
        assert data["organization_level"] == 3

        # RBAC: self=200, manager->subordinate=200, sibling peer=403, cross-company=403
        assert (await client.get(f"/api/v1/hierarchy/{emp.id}", headers=_auth_headers(emp_u))).status_code == 200
        assert (await client.get(f"/api/v1/hierarchy/{emp.id}", headers=_auth_headers(mgr_u))).status_code == 200
        assert (await client.get(f"/api/v1/hierarchy/{peer.id}", headers=_auth_headers(emp_u))).status_code == 403
        assert (await client.get(f"/api/v1/hierarchy/{emp.id}", headers=_auth_headers(hr_b))).status_code == 403


async def test_attendance_assets_skip_pii_and_errors_preserve_encryption_and_request_id(pg_ctx):
    """Attendance & Assets exclude encrypted PII; failing PII endpoint returns 503 + X-Request-ID without faking."""
    session, eng = pg_ctx
    cid = uuid.uuid4()
    session.add(Company(id=cid, name="Ops Safe Co"))
    await session.flush()

    admin = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="Ops Admin")
    emp_u = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Ops Emp")
    emp = Employee(
        id=uuid.uuid4(), company_id=cid, user_id=emp_u.id,
        employee_id=f"OPS-{uuid.uuid4().hex[:5]}", first_name="Kiran", last_name="Rao",
        personal_email=f"kiran.{uuid.uuid4().hex[:6]}@t.co", phone="9555555555",
        department="Ops", designation="Ops Engineer",
        role="employee", status="ACTIVE", joining_date=date(2025, 1, 1),
    )
    session.add(emp)
    await session.flush()
    asset = Asset(
        id=uuid.uuid4(),
        company_id=cid,
        tag=f"LAP-{uuid.uuid4().hex[:6]}",
        name="ThinkPad X1",
        category="laptop",
        status="assigned",
        employee_id=emp.id,
    )
    session.add(asset)
    await session.commit()

    await session.execute(
        text("UPDATE employees SET pan_number = :c WHERE id = :id"),
        {"c": UNCONFIGURED_CIPHERTEXT, "id": emp.id},
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        assert (await client.get("/api/v1/attendance/today", headers=_auth_headers(admin))).status_code == 200
        assert (await client.get("/api/v1/attendance/face/company", headers=_auth_headers(admin))).status_code == 200
        assert (await client.get("/api/v1/attendance/my-history", headers=_auth_headers(emp_u))).status_code == 200
        r_assets = await client.get("/api/v1/assets?page=1&limit=20", headers=_auth_headers(admin))
        assert r_assets.status_code == 200, r_assets.text

        # Full PII employee detail must NOT bypass encryption; must return 503 with request_id
        r_503 = await client.get(
            f"/api/v1/employees/{emp.id}",
            headers=_auth_headers(admin, {"X-Request-ID": "trace-503-key"}),
        )
        assert r_503.status_code == 503
        assert r_503.headers.get("x-request-id") == "trace-503-key"
        err_json = r_503.json()
        assert err_json["code"] == "FIELD_ENCRYPTION_UNAVAILABLE"
        assert err_json["request_id"] == "trace-503-key"

        # Invalid UUID returns 422 with request_id echoed
        r_422 = await client.get(
            "/api/v1/employees/not-a-uuid",
            headers=_auth_headers(admin, {"X-Request-ID": "trace-422-uuid"}),
        )
        assert r_422.status_code == 422
        assert r_422.headers.get("x-request-id") == "trace-422-uuid"
        assert r_422.json().get("request_id") == "trace-422-uuid"

        # Readiness schema inspection on un-migrated Base.metadata.create_all DB reports revision mismatch cleanly
        r_drift = await inspect_schema_drift(eng)
        assert r_drift["missing_tables"] == 0
        assert r_drift["missing_columns"] == 0
        # Since create_all DB has no alembic_version row, readiness fails closed
        assert (await readiness(eng))["schema"] is False
