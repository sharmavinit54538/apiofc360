"""Isolated PostgreSQL 18 regression tests for the three Employee Detail errors."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.field_encryption import ENCRYPTED_VALUE_PREFIX, encrypt_value
from app.core.security import create_access_token, hash_password
from app.db.base import Base, tenant_id_ctx
from app.db.database import get_db_session
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models.company import Company
from app.models.document import DocumentCategory
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.payroll import ReimbursementClaim
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
KEY_ACTIVE = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
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
    """Boot a temporary private PG18 cluster so tests never touch equnixsphere_prod."""
    if not (PG_BIN / "initdb.exe").exists():
        pytest.skip("PostgreSQL 18 binaries not available for isolated PG test cluster")

    port = _free_port()
    tmp_dir = Path(tempfile.mkdtemp(prefix="pg_emp_detail_err_"))
    pgdata = tmp_dir / "pgdata"
    logfile = tmp_dir / "pg.log"
    db_name = "ofc360_emp_detail_test"

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
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_ACTIVE))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_ACTIVE)

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
            yield s
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


def _auth_headers(user: User, permissions: list[str] | None = None) -> dict[str, str]:
    claims = {
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "company_id": str(user.company_id) if user.company_id else None,
        "email": user.email,
    }
    if permissions is not None:
        claims["permissions"] = permissions
    tok = create_access_token(
        subject=str(user.id),
        claims=claims,
    )
    return {"Authorization": f"Bearer {tok}"}


async def test_documents_compensation_expenses_succeed_with_unconfigured_key_pii(pg_ctx):
    """Non-PII Employee Detail endpoints succeed (200) even when PII uses missing key 0eb07e19bb3a."""
    session = pg_ctx
    cid = uuid.uuid4()
    session.add(Company(id=cid, name="Non-PII Isolation Corp"))
    await session.flush()

    admin = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="HR Admin")
    emp_user = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Legacy Emp")

    emp = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=emp_user.id,
        employee_id=f"LEG-{uuid.uuid4().hex[:5]}",
        first_name="Asha",
        last_name="Verma",
        personal_email=f"asha.{uuid.uuid4().hex[:6]}@example.test",
        company_email=f"asha.work.{uuid.uuid4().hex[:6]}@example.test",
        phone="9888877777",
        department="Finance",
        designation="Analyst",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 2, 1),
    )
    session.add(emp)
    await session.flush()

    cat = DocumentCategory(
        id=uuid.uuid4(),
        name="Government ID",
        code=f"GOV_{uuid.uuid4().hex[:6]}",
        is_company=False,
    )
    session.add(cat)
    await session.flush()

    doc = EmployeeDocument(
        id=uuid.uuid4(),
        employee_id=emp.id,
        category_id=cat.id,
        uploaded_by=admin.id,
        title="Existing PAN Document",
        file_name="pan.pdf",
        file_size=20480,
        file_path="uploads/test-pan.pdf",
        status="VERIFIED",
        is_verified=True,
        visibility="PRIVATE",
        ocr_status="NOT_STARTED",
    )
    session.add(doc)

    claim = ReimbursementClaim(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp.id,
        category="TRAVEL",
        amount=Decimal("2450.00"),
        currency="INR",
        description="Client visit cab",
        claim_date=date(2026, 10, 15),
        status="SUBMITTED",
        payout_mode="STANDALONE",
    )
    session.add(claim)
    await session.commit()

    # Corrupt encrypted PII with missing key_id=0eb07e19bb3a
    await session.execute(
        text("UPDATE employees SET pan_number = :c, aadhaar_number = :c WHERE id = :id"),
        {"c": UNCONFIGURED_CIPHERTEXT, "id": emp.id},
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        # 1. Documents list & get (both admin and owner employee) succeed without decrypting PII
        r_docs = await client.get(
            f"/api/v1/documents/employees?employee_id={emp.id}&limit=50",
            headers=_auth_headers(admin),
        )
        assert r_docs.status_code == 200, r_docs.text
        docs_data = r_docs.json()["data"]
        assert len(docs_data) == 1
        assert docs_data[0]["id"] == str(doc.id)
        assert docs_data[0]["title"] == "Existing PAN Document"
        assert docs_data[0]["employee_name"] == "Asha Verma"

        r_docs_self = await client.get(
            f"/api/v1/documents/employees/{doc.id}",
            headers=_auth_headers(emp_user),
        )
        assert r_docs_self.status_code == 200, r_docs_self.text

        # 2. Payroll compensation auto-provisions & reads without decrypting PII
        r_comp = await client.get(
            f"/api/v2/payroll/employees/{emp.id}/compensation",
            headers=_auth_headers(admin),
        )
        assert r_comp.status_code == 200, r_comp.text
        assert r_comp.json()["data"]["ctc_annual_paise"] > 0

        r_comp_self = await client.get(
            f"/api/v2/payroll/employees/{emp.id}/compensation",
            headers=_auth_headers(emp_user),
        )
        assert r_comp_self.status_code == 200, r_comp_self.text

        # 3. Real expenses route (/api/v1/expenses) returns 200 without decrypting PII; /api/v2/expenses is 404
        r_exp = await client.get(
            f"/api/v1/expenses?employee_id={emp.id}&page=1&limit=30",
            headers=_auth_headers(admin, permissions=["expenses:read"]),
        )
        assert r_exp.status_code == 200, r_exp.text
        exp_payload = r_exp.json()["data"]
        assert exp_payload["total"] == 1
        assert exp_payload["items"][0]["id"] == str(claim.id)
        assert exp_payload["items"][0]["employee"]["name"] == "Asha Verma"

        r_v2_404 = await client.get(
            "/api/v2/expenses?search=Asha&limit=30",
            headers=_auth_headers(admin, permissions=["expenses:read"]),
        )
        assert r_v2_404.status_code == 404


async def test_expenses_isolate_same_name_employees_by_employee_id(pg_ctx):
    """Two employees with identical names cannot see each other's expenses via employee_id filter."""
    session = pg_ctx
    cid = uuid.uuid4()
    session.add(Company(id=cid, name="Same Name Corp"))
    await session.flush()

    admin = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="Expense Admin")
    u1 = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Vinit One")
    u2 = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Vinit Two")

    emp_1 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=u1.id,
        employee_id=f"DUP-{uuid.uuid4().hex[:5]}",
        first_name="Vinit",
        last_name="Sharma",
        personal_email=f"vinit1.{uuid.uuid4().hex[:6]}@example.test",
        phone="9111111111",
        department="Engineering",
        designation="Engineer",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 3, 1),
    )
    emp_2 = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=u2.id,
        employee_id=f"DUP-{uuid.uuid4().hex[:5]}",
        first_name="Vinit",
        last_name="Sharma",
        personal_email=f"vinit2.{uuid.uuid4().hex[:6]}@example.test",
        phone="9222222222",
        department="Sales",
        designation="Executive",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 4, 1),
    )
    session.add_all([emp_1, emp_2])
    await session.flush()

    c1 = ReimbursementClaim(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp_1.id,
        category="TRAVEL",
        amount=Decimal("1500.00"),
        currency="INR",
        description="Vinit 1 Flight",
        claim_date=date(2026, 11, 1),
        status="SUBMITTED",
        payout_mode="STANDALONE",
    )
    c2 = ReimbursementClaim(
        id=uuid.uuid4(),
        company_id=cid,
        employee_id=emp_2.id,
        category="MEALS",
        amount=Decimal("850.00"),
        currency="INR",
        description="Vinit 2 Dinner",
        claim_date=date(2026, 11, 2),
        status="APPROVED",
        payout_mode="STANDALONE",
    )
    session.add_all([c1, c2])
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        r1 = await client.get(
            f"/api/v1/expenses?employee_id={emp_1.id}&page=1&limit=30",
            headers=_auth_headers(admin, permissions=["expenses:read"]),
        )
        assert r1.status_code == 200
        d1 = r1.json()["data"]
        assert d1["total"] == 1
        assert [item["id"] for item in d1["items"]] == [str(c1.id)]

        r2 = await client.get(
            f"/api/v1/expenses?employee_id={emp_2.id}&page=1&limit=30",
            headers=_auth_headers(admin, permissions=["expenses:read"]),
        )
        assert r2.status_code == 200
        d2 = r2.json()["data"]
        assert d2["total"] == 1
        assert [item["id"] for item in d2["items"]] == [str(c2.id)]

        # Self-service user u1 cannot query u2's expenses even though both are named Vinit Sharma
        r_cross = await client.get(
            f"/api/v1/expenses?employee_id={emp_2.id}&page=1&limit=30",
            headers=_auth_headers(u1),
        )
        assert r_cross.status_code == 200
        assert r_cross.json()["data"]["total"] == 0


async def test_reset_password_succeeds_for_disposable_and_fails_closed_for_missing_key(pg_ctx):
    """Reset Password works with active key and fails closed (503) when key_id is missing."""
    session = pg_ctx
    cid = uuid.uuid4()
    session.add(Company(id=cid, name="Reset Key Corp"))
    await session.flush()

    admin = await _make_user(session, company_id=cid, role=UserRole.HR_ADMIN, name="Reset Admin")
    u_ok = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="Clean Emp")
    u_bad = await _make_user(session, company_id=cid, role=UserRole.EMPLOYEE, name="BadKey Emp")

    emp_ok = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=u_ok.id,
        employee_id=f"OK-{uuid.uuid4().hex[:5]}",
        first_name="Clean",
        last_name="Employee",
        personal_email=f"clean.{uuid.uuid4().hex[:6]}@example.test",
        phone="9333333333",
        department="Ops",
        designation="Lead",
        pan_number=encrypt_value("ABCDE1234F"),
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 5, 1),
    )
    emp_bad = Employee(
        id=uuid.uuid4(),
        company_id=cid,
        user_id=u_bad.id,
        employee_id=f"BAD-{uuid.uuid4().hex[:5]}",
        first_name="Legacy",
        last_name="Employee",
        personal_email=f"bad.{uuid.uuid4().hex[:6]}@example.test",
        phone="9444444444",
        department="Ops",
        designation="Lead",
        role="employee",
        status="ACTIVE",
        joining_date=date(2025, 5, 1),
    )
    session.add_all([emp_ok, emp_bad])
    await session.commit()

    await session.execute(
        text("UPDATE employees SET pan_number = :c WHERE id = :id"),
        {"c": UNCONFIGURED_CIPHERTEXT, "id": emp_bad.id},
    )
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        r_ok = await client.post(
            f"/api/v1/employees/{emp_ok.id}/reset-password",
            headers=_auth_headers(admin),
        )
        assert r_ok.status_code == 200, r_ok.text
        assert r_ok.json()["success"] is True

        r_bad_reset = await client.post(
            f"/api/v1/employees/{emp_bad.id}/reset-password",
            headers=_auth_headers(admin),
        )
        assert r_bad_reset.status_code == 503
        assert r_bad_reset.json()["code"] == "FIELD_ENCRYPTION_UNAVAILABLE"

        r_bad_onb = await client.get(
            f"/api/v1/admin/employee-onboarding/{emp_bad.id}",
            headers=_auth_headers(admin),
        )
        assert r_bad_onb.status_code == 503
        assert r_bad_onb.json()["code"] == "FIELD_ENCRYPTION_UNAVAILABLE"
