"""Isolated PostgreSQL regression suite for compliance schema migration, field encryption hardening, payroll dashboard, leave endpoints, and department query performance."""

from __future__ import annotations

import base64
import importlib.util
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import database_exception_handler, field_encryption_exception_handler
from app.core.field_encryption import (
    ENCRYPTED_VALUE_PREFIX,
    FieldEncryptionError,
    active_key_id,
    configured_key_ids,
    decrypt_value,
    encrypt_value,
    reencrypt_value,
    validate_encryption_configuration,
)
from app.core.security import create_access_token, hash_password
from app.db.base import Base, tenant_id_ctx
from app.db.database import get_db_session
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.payroll import (
    PayrollRun,
    Payslip,
    StatutoryComplianceConfig,
)
from app.models.payroll_compliance import ComplianceDueDate, PayrollCompliance
from app.models.payroll_models import PaymentBatch, PaymentBatchItem, PayrollPeriod, PayrollRunEmployee
from app.models.user import User, UserRole
from app.repositories.employee_repository import EmployeeRepository

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[1]
PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
KEY_OLD = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
KEY_NEW = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"


def _load_migration(filename: str):
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture(scope="module")
async def pg_cluster_url():
    """Boot a temporary private PG18 cluster (or reuse PAYROLL_POSTGRES_TEST_URL) without touching equnixsphere_prod."""
    env_url = os.getenv("PAYROLL_POSTGRES_TEST_URL")
    if env_url:
        yield env_url
        return
    if not (PG_BIN / "initdb.exe").exists():
        pytest.skip("PostgreSQL 18 binaries not available for isolated PG test cluster")

    port = _free_port()
    tmp_dir = Path(tempfile.mkdtemp(prefix="pg_fixes_test_"))
    pgdata = tmp_dir / "pgdata"
    logfile = tmp_dir / "pg.log"
    db_name = "ofc360_fixes_test"

    subprocess.run(
        [str(PG_BIN / "initdb.exe"), "-D", str(pgdata), "-U", "postgres", "-A", "trust", "--encoding=UTF8"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    subprocess.run(
        [str(PG_BIN / "pg_ctl.exe"), "-D", str(pgdata), "-l", str(logfile), "-o", f"-p {port} -F", "start"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        subprocess.run(
            [str(PG_BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", db_name],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        url = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{port}/{db_name}"
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()
        yield url
    finally:
        subprocess.run(
            [str(PG_BIN / "pg_ctl.exe"), "-D", str(pgdata), "stop", "-m", "immediate"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def pg_session(pg_cluster_url, monkeypatch):
    """Per-test session with FastAPI get_db_session override against the isolated PG database."""
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_NEW))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_NEW)

    eng = create_async_engine(pg_cluster_url, poolclass=NullPool)
    session_factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db():
        async with session_factory() as s:
            try:
                yield s
            finally:
                tenant_id_ctx.set(None)

    fastapi_app.dependency_overrides[get_db_session] = _override_get_db
    try:
        async with session_factory() as s:
            yield s
    finally:
        fastapi_app.dependency_overrides.pop(get_db_session, None)
        tenant_id_ctx.set(None)
        await eng.dispose()


async def _seed_user(
    session: AsyncSession,
    *,
    company_id: uuid.UUID,
    role: UserRole,
    name: str,
    email: str,
) -> User:
    u = User(
        id=uuid.uuid4(),
        company_id=company_id,
        name=name,
        email=email,
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


def _auth_header(user: User) -> dict[str, str]:
    tok = create_access_token(
        subject=str(user.id),
        claims={
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "company_id": str(user.company_id) if user.company_id else None,
            "email": user.email,
        },
    )
    return {"Authorization": f"Bearer {tok}"}


# ==============================================================================
# 1. Compliance Migration & Composite Index Migration Tests (PostgreSQL)
# ==============================================================================

async def test_compliance_due_date_and_perf_index_migrations_preserve_data(pg_cluster_url):
    """Simulate drifted DB missing filing_frequency/metadata columns & indexes, run migrations, and verify row preservation."""
    mig_due = _load_migration("9bed212c8289_sync_payroll_compliance_due_date_schema.py")
    mig_idx = _load_migration("5eacbae59559_add_composite_indexes_for_departments_.py")

    eng = create_async_engine(pg_cluster_url, poolclass=NullPool)
    async with eng.connect() as conn:
        trans = await conn.begin()
        try:
            # Create tenant + parent compliance rule + drifted due_dates schema inside rollback-safe transaction
            cid = uuid.uuid4()
            comp_rule_id = uuid.uuid4()
            await conn.execute(text("INSERT INTO companies (id, name) VALUES (:id, :name)"), {"id": cid, "name": f"MigCo-{cid.hex[:6]}"})
            await conn.execute(
                text("""
                    INSERT INTO payroll_compliance (id, compliance_code, compliance_name, category, filing_frequency, due_day_of_month, state)
                    VALUES (:id, :code, 'Quarterly Rule', 'STATUTORY', 'QUARTERLY', 15, 'ALL_INDIA')
                """),
                {"id": comp_rule_id, "code": f"Q_{cid.hex[:6]}"},
            )

            # Revert migrations inside this transaction to simulate legacy pre-migration DB
            def _run_downgrade(sc):
                with Operations.context(MigrationContext.configure(sc)):
                    mig_idx.downgrade()
                    mig_due.downgrade()
            await conn.run_sync(_run_downgrade)

            # Insert drifted rows (1 unlinked EPFO monthly row, 1 linked quarterly row)
            row_epfo = uuid.uuid4()
            row_linked = uuid.uuid4()
            await conn.execute(
                text("""
                    INSERT INTO payroll_compliance_due_dates
                    (id, compliance_id, company_id, title, due_date, period, period_month, period_year, status, is_overdue, overdue_days, interest_7q_amount, damages_14b_amount)
                    VALUES
                    (:id1, NULL, :cid, 'EPFO PF & ECR Filing - May 2026', '2026-06-15', 'May 2026', 5, 2026, 'ECR_GENERATED', false, 0, 0, 0),
                    (:id2, :comp_id, :cid, 'Quarterly Statutory Return', '2026-07-15', 'Q1 2026', 6, 2026, 'PENDING', false, 0, 0, 0)
                """),
                {"id1": row_epfo, "id2": row_linked, "cid": cid, "comp_id": comp_rule_id},
            )

            # Upgrade + idempotent re-run
            def _run_upgrade(sc):
                with Operations.context(MigrationContext.configure(sc)):
                    mig_due.upgrade()
                    mig_due.upgrade()  # idempotent
                    mig_idx.upgrade()
                    mig_idx.upgrade()  # idempotent
            await conn.run_sync(_run_upgrade)

            rows = (
                await conn.execute(
                    text("SELECT id, filing_frequency, status FROM payroll_compliance_due_dates WHERE id IN (:i1, :i2)"),
                    {"i1": row_epfo, "i2": row_linked},
                )
            ).mappings().all()
            by_id = {r["id"]: r for r in rows}
            assert by_id[row_epfo]["filing_frequency"] == "MONTHLY"
            assert by_id[row_epfo]["status"] == "ECR_GENERATED"
            assert by_id[row_linked]["filing_frequency"] == "QUARTERLY"

            # Verify indexes created
            idx_names = set(
                (await conn.execute(text("""
                    SELECT indexname FROM pg_indexes WHERE tablename IN ('payroll_compliance_due_dates', 'departments', 'employees', 'leave_requests')
                """))).scalars().all()
            )
            assert {
                "ix_payroll_compliance_due_dates_company",
                "ix_departments_company_active_created",
                "ix_employees_company_dept_status",
                "ix_employees_company_name_sort",
                "ix_leave_requests_emp_sort",
                "ix_leave_requests_status_sort",
            }.issubset(idx_names)

            # Verify unclassifiable legacy row without compliance_id aborts instead of guessing arbitrary default
            def _drop_freq(sc):
                with Operations.context(MigrationContext.configure(sc)):
                    mig_due.downgrade()
            await conn.run_sync(_drop_freq)
            await conn.execute(
                text("""
                    INSERT INTO payroll_compliance_due_dates
                    (id, compliance_id, company_id, title, due_date, period, period_month, period_year, status, is_overdue, overdue_days, interest_7q_amount, damages_14b_amount)
                    VALUES (:id, NULL, :cid, 'Custom Ambiguous Filing', '2026-08-20', 'Jul 2026', 7, 2026, 'PENDING', false, 0, 0, 0)
                """),
                {"id": uuid.uuid4(), "cid": cid},
            )
            def _run_due_upgrade(sc):
                with Operations.context(MigrationContext.configure(sc)):
                    mig_due.upgrade()
            with pytest.raises(RuntimeError, match="could not be matched"):
                await conn.run_sync(_run_due_upgrade)
        finally:
            await trans.rollback()
    await eng.dispose()


# ==============================================================================
# 2. Field Encryption & Centralized Exception Handler Tests
# ==============================================================================

async def test_encryption_keyring_rotation_dedup_and_fail_closed(monkeypatch):
    """Verify rotated keys decrypt cleanly, duplicate encodings dedup cleanly, and missing key fails closed."""
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_OLD))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_OLD)
    old_id = active_key_id()
    old_cipher = encrypt_value("ABCDE1234F")

    # Configure new key first, plus old key in both hex and base64 forms -> duplicates deduped by key_id
    b64_new = base64.urlsafe_b64encode(bytes.fromhex(KEY_NEW)).decode("ascii")
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(f"{KEY_NEW},{b64_new},{KEY_OLD}"))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", f"{KEY_NEW},{b64_new},{KEY_OLD}")
    info = validate_encryption_configuration()
    assert info["configured"] is True
    assert info["key_count"] == 2
    assert len(configured_key_ids()) == 2
    assert old_id in info["retained_key_ids"]
    assert decrypt_value(old_cipher) == "ABCDE1234F"

    rotated = reencrypt_value(old_cipher)
    assert rotated is not None and rotated.startswith(f"{ENCRYPTED_VALUE_PREFIX}{info['active_key_id']}:")

    # Remove old key -> missing key raises FieldEncryptionError and never exposes raw key or ciphertext
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_NEW))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_NEW)
    with pytest.raises(FieldEncryptionError, match=old_id):
        decrypt_value(old_cipher)

    # Handler renders HTTP 503 cleanly with zero secret or ciphertext leaks
    fake_req = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/v1/employees"),
        headers={},
        state=SimpleNamespace(user_claims={"sub": "u1", "role": "hr_admin"}),
    )
    resp = await field_encryption_exception_handler(
        fake_req,
        FieldEncryptionError(f"The key required by this encrypted field is not configured (key_id={old_id}). Retain previous keys during rotation."),
    )
    assert resp.status_code == 503
    body = resp.body.decode("utf-8")
    assert "FIELD_ENCRYPTION_UNAVAILABLE" in body
    assert KEY_OLD not in body and KEY_NEW not in body and old_cipher not in body

    # SQLSTATE 42703 UndefinedColumnError handler renders 500 cleanly without leaking column/SQL names
    orig = SimpleNamespace(sqlstate="42703")
    prog_exc = ProgrammingError("SELECT secret_col FROM tbl", {}, Exception("column secret_col does not exist"))
    prog_exc.orig = orig
    db_resp = await database_exception_handler(fake_req, prog_exc)
    assert db_resp.status_code == 500
    db_body = db_resp.body.decode("utf-8")
    assert "DATABASE_ERROR" in db_body
    assert "secret_col" not in db_body


# ==============================================================================
# 3. End-to-End API Integration Tests: Payroll Dashboard & Leave Endpoints (PG)
# ==============================================================================

async def test_payroll_dashboard_and_leave_endpoints_end_to_end(pg_session: AsyncSession, monkeypatch):
    """Verify Payroll Dashboard (200 OK), Leave Employees/Balances/History/Pending (200 OK), legacy-key resilience, and tenant isolation."""
    # Seed Tenant A and Tenant B
    comp_a = Company(id=uuid.uuid4(), name=f"TenantA-{uuid.uuid4().hex[:6]}", currency="INR")
    comp_b = Company(id=uuid.uuid4(), name=f"TenantB-{uuid.uuid4().hex[:6]}", currency="INR")
    pg_session.add_all([comp_a, comp_b])
    await pg_session.flush()

    admin_a = await _seed_user(pg_session, company_id=comp_a.id, role=UserRole.HR_ADMIN, name="Asha Admin", email=f"admina-{uuid.uuid4().hex[:6]}@test.local")
    emp_user_a = await _seed_user(pg_session, company_id=comp_a.id, role=UserRole.EMPLOYEE, name="Rohan Emp", email=f"empa-{uuid.uuid4().hex[:6]}@test.local")
    admin_b = await _seed_user(pg_session, company_id=comp_b.id, role=UserRole.HR_ADMIN, name="Bala Admin", email=f"adminb-{uuid.uuid4().hex[:6]}@test.local")

    dept_a = Department(
        id=uuid.uuid4(),
        company_id=comp_a.id,
        department_code=f"ENG-{uuid.uuid4().hex[:4].upper()}",
        department_name=f"Engineering-{uuid.uuid4().hex[:4]}",
        description="Engineering Dept",
        location="HQ",
        manager_id=admin_a.id,
        status="ACTIVE",
        is_deleted=False,
    )
    pg_session.add(dept_a)
    await pg_session.flush()

    # Employee 1: encrypted with current KEY_NEW
    emp_a1 = Employee(
        id=uuid.uuid4(),
        user_id=emp_user_a.id,
        company_id=comp_a.id,
        employee_id=f"EA1-{uuid.uuid4().hex[:8]}",
        first_name="Rohan",
        last_name="Verma",
        personal_email=f"ea1-{uuid.uuid4().hex[:6]}@test.local",
        phone="9876543210",
        department=dept_a.department_name,
        department_id=dept_a.id,
        designation="Senior Engineer",
        joining_date=date(2025, 1, 10),
        status="ACTIVE",
        employment_status="ACTIVE",
        is_active=True,
        is_deleted=False,
        pan_number="ABCDE1234F",
    )
    # Employee 2 in Tenant A: simulate ciphertext encrypted with historical KEY_OLD (0eb07e19bb3a-equivalent missing key!)
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_OLD))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_OLD)
    legacy_pan_cipher = encrypt_value("ZZZZZ9999Z")
    legacy_aadhaar_cipher = encrypt_value("123412341234")
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(KEY_NEW))
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", KEY_NEW)

    emp_a2 = Employee(
        id=uuid.uuid4(),
        company_id=comp_a.id,
        employee_id=f"EA2-{uuid.uuid4().hex[:8]}",
        first_name="Meera",
        last_name="Kapoor",
        personal_email=f"ea2-{uuid.uuid4().hex[:6]}@test.local",
        phone="9876543211",
        department=dept_a.department_name,
        department_id=dept_a.id,
        designation="Payroll Specialist",
        joining_date=date(2025, 2, 1),
        status="ACTIVE",
        employment_status="ACTIVE",
        is_active=True,
        is_deleted=False,
    )
    # Tenant B employee (must NEVER leak to Tenant A)
    emp_b1 = Employee(
        id=uuid.uuid4(),
        company_id=comp_b.id,
        employee_id=f"EB1-{uuid.uuid4().hex[:8]}",
        first_name="SecretTenantB",
        last_name="User",
        personal_email=f"eb1-{uuid.uuid4().hex[:6]}@test.local",
        phone="9876543212",
        department="Finance",
        designation="Analyst",
        joining_date=date(2025, 3, 1),
        status="ACTIVE",
        employment_status="ACTIVE",
        is_active=True,
        is_deleted=False,
    )
    pg_session.add_all([emp_a1, emp_a2, emp_b1])
    await pg_session.flush()

    # Write historical missing-key ciphertext directly via SQL so emp_a2 mirrors equnixsphere_prod row
    await pg_session.execute(
        text("UPDATE employees SET pan_number = :pan, aadhaar_number = :aad WHERE id = :id").execution_options(tenant_safe=True),
        {"pan": legacy_pan_cipher, "aad": legacy_aadhaar_cipher, "id": emp_a2.id},
    )

    # Seed PayrollPeriod + Run + Payslip + ComplianceDueDate (Nov 2026) for Tenant A
    period_nov = PayrollPeriod(
        id=uuid.uuid4(),
        company_id=comp_a.id,
        name="November 2026",
        period_month=11,
        period_year=2026,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 12, 1),
        status="PROCESSED",
    )
    pg_session.add(period_nov)
    await pg_session.flush()

    run_nov = PayrollRun(
        id=uuid.uuid4(),
        company_id=comp_a.id,
        period_id=period_nov.id,
        run_number=f"RUN-202611-{uuid.uuid4().hex[:4]}",
        period_month=11,
        period_year=2026,
        status="PROCESSED",
        validation_status="VALIDATED",
        total_employees=1,
        total_gross=Decimal("100000.00"),
        total_deductions=Decimal("12000.00"),
        total_net=Decimal("88000.00"),
        total_gross_paise=10000000,
        total_deductions_paise=1200000,
        total_net_paise=8800000,
    )
    pg_session.add(run_nov)
    await pg_session.flush()

    pg_session.add(
        Payslip(
            id=uuid.uuid4(),
            company_id=comp_a.id,
            payroll_run_id=run_nov.id,
            employee_id=emp_a1.id,
            payslip_number=f"PAY-202611-{uuid.uuid4().hex[:6]}",
            period_month=11,
            period_year=2026,
            total_days_in_month=30,
            paid_days=Decimal("30.0"),
            gross_earnings=Decimal("100000.00"),
            total_deductions=Decimal("12000.00"),
            net_pay=Decimal("88000.00"),
            employee_pf=Decimal("1800.00"),
            employer_pf=Decimal("1800.00"),
            employer_esi=Decimal("0.00"),
            professional_tax=Decimal("200.00"),
            tds=Decimal("10000.00"),
            payment_status="PAID",
        )
    )
    pg_session.add(
        PayrollRunEmployee(
            id=uuid.uuid4(),
            company_id=comp_a.id,
            run_id=run_nov.id,
            employee_id=emp_a1.id,
            gross_earnings_paise=10000000,
            total_deductions_paise=1200000,
            net_pay_paise=8800000,
            validation_status="VALIDATED",
        )
    )
    batch = PaymentBatch(
        id=uuid.uuid4(),
        company_id=comp_a.id,
        run_id=run_nov.id,
        batch_number=f"PB-{uuid.uuid4().hex[:6]}",
        source_account_id="ACC-TEST-001",
        status="COMPLETED",
    )
    pg_session.add(batch)
    await pg_session.flush()
    pg_session.add(
        PaymentBatchItem(
            id=uuid.uuid4(),
            batch_id=batch.id,
            employee_id=emp_a1.id,
            amount_paise=8800000,
            status="PAID",
        )
    )
    pg_session.add(
        ComplianceDueDate(
            id=uuid.uuid4(),
            company_id=comp_a.id,
            period_id=period_nov.id,
            title="EPFO PF & ECR Filing - November 2026",
            due_date=date(2026, 12, 15),
            period="November 2026",
            period_month=11,
            period_year=2026,
            status="ECR_GENERATED",
            filing_frequency="MONTHLY",
        )
    )
    pg_session.add(
        StatutoryComplianceConfig(
            id=uuid.uuid4(),
            company_id=comp_a.id,
            company_name="Tenant A",
            pf_enabled=True,
            esi_enabled=True,
            is_active=True,
        )
    )

    # Seed 1 Pending leave + 1 Reviewed leave (reviewed_by -> User.name, verifying reviewed_by_name property)
    pg_session.add_all([
        LeaveRequest(
            id=uuid.uuid4(),
            employee_id=emp_a2.id,
            leave_type="Casual Leave",
            start_date=date(2026, 11, 28),
            end_date=date(2026, 11, 28),
            total_days=Decimal("1.0"),
            reason="Personal errand",
            status="PENDING",
        ),
        LeaveRequest(
            id=uuid.uuid4(),
            employee_id=emp_a1.id,
            leave_type="Sick Leave",
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 10),
            total_days=Decimal("1.0"),
            reason="Fever",
            status="APPROVED",
            approved_by_id=admin_a.id,
            reviewed_by_id=admin_a.id,
            reviewed_at=datetime.now(timezone.utc),
        ),
    ])
    await pg_session.commit()

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Payroll Dashboard (explicit period & default period)
        r_dash = await client.get("/api/v1/payroll/dashboard?month=11&year=2026", headers=_auth_header(admin_a))
        assert r_dash.status_code == 200, r_dash.text
        dash_json = r_dash.json()
        assert dash_json["success"] is True
        d = dash_json["data"]
        assert d["summary"]["total_gross"] == 100000.0
        assert d["summary"]["total_deductions"] == 12000.0
        assert d["summary"]["total_net"] == 88000.0
        assert d["employer_contributions"]["employer_pf"] == 1800.0
        assert d["statutory_summary"]["pending_filings_count"] == 1
        assert d["payment_summary"]["paid_count"] == 1
        # Readiness check must NOT flag emp_a2 (who has legacy-key ciphertext PAN) as missing PAN
        missing_pan_warnings = [w for w in d["issues"]["warnings"] if "Missing PAN number" in w["message"]]
        assert not missing_pan_warnings

        # Empty historical period returns clean zero metrics with 200
        r_hist_dash = await client.get("/api/v1/payroll/dashboard?month=1&year=2025", headers=_auth_header(admin_a))
        assert r_hist_dash.status_code == 200
        assert r_hist_dash.json()["data"]["status"] == "NOT_STARTED"
        assert r_hist_dash.json()["data"]["summary"]["total_gross"] == 0.0

        # Cross-tenant isolation: Tenant B must not see Tenant A's payroll or compliance filings
        r_b_dash = await client.get("/api/v1/payroll/dashboard?month=11&year=2026", headers=_auth_header(admin_b))
        assert r_b_dash.status_code == 200
        assert r_b_dash.json()["data"]["summary"]["total_gross"] == 0.0
        assert r_b_dash.json()["data"]["statutory_summary"]["pending_filings_count"] == 0

        # Unauthorized / Role checks
        assert (await client.get("/api/v1/payroll/dashboard")).status_code == 401
        assert (await client.get("/api/v1/payroll/dashboard", headers=_auth_header(emp_user_a))).status_code == 403

        # 2. Leave Employees: MUST succeed with 200 even when emp_a2 has unconfigured historical-key PII!
        r_emps = await client.get("/api/v1/leaves/employees?q=&page=1&limit=50", headers=_auth_header(admin_a))
        assert r_emps.status_code == 200, r_emps.text
        emp_items = r_emps.json()["data"]
        names = [it["full_name"] for it in emp_items]
        assert names == ["Meera Kapoor", "Rohan Verma"]  # alphabetical, Tenant B excluded
        assert all("pan_number" not in it and "aadhaar_number" not in it for it in emp_items)

        # Search + pagination
        r_search = await client.get("/api/v1/leaves/employees?q=Meera&page=1&limit=50", headers=_auth_header(admin_a))
        assert r_search.status_code == 200
        assert [it["full_name"] for it in r_search.json()["data"]] == ["Meera Kapoor"]
        r_page2 = await client.get("/api/v1/leaves/employees?q=&page=2&limit=1", headers=_auth_header(admin_a))
        assert r_page2.status_code == 200
        assert [it["full_name"] for it in r_page2.json()["data"]] == ["Rohan Verma"]

        # 3. Leave Balances, History, Pending, Requests & Departments
        r_bal1 = await client.get("/api/v1/leaves/balances", headers=_auth_header(emp_user_a))
        assert r_bal1.status_code == 200
        assert len(r_bal1.json()["data"]) == 4
        r_bal2 = await client.get("/api/v1/leaves/balances", headers=_auth_header(emp_user_a))
        assert r_bal2.status_code == 200

        r_hist = await client.get("/api/v1/leaves/history", headers=_auth_header(emp_user_a))
        assert r_hist.status_code == 200
        assert r_hist.json()["data"][0]["reviewed_by_name"] == "Asha Admin"

        r_pend = await client.get("/api/v1/leaves/pending", headers=_auth_header(admin_a))
        assert r_pend.status_code == 200
        assert len(r_pend.json()["data"]) == 1
        assert r_pend.json()["data"][0]["employee_name"] == "Meera Kapoor"

        r_reqs = await client.get("/api/v1/leaves/requests", headers=_auth_header(admin_a))
        assert r_reqs.status_code == 200
        assert len(r_reqs.json()["data"]) == 2

        r_depts = await client.get("/api/v1/departments", headers=_auth_header(admin_a))
        assert r_depts.status_code == 200
        assert r_depts.json()["data"]["items"][0]["manager_name"] == "Asha Admin"

        # 4. Full PII access on emp_a2 STILL fails closed cleanly with FieldEncryptionError!
        with pytest.raises(FieldEncryptionError, match="not configured"):
            await EmployeeRepository(pg_session).get_by_id(emp_a2.id)
