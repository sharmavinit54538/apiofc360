"""Comprehensive regression suite for field encryption, employee API, manager sync, exception handling, and event-loop fixes."""

from __future__ import annotations

import ast
import time
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, settings
from app.core.exceptions import install_exception_handlers
from app.core.field_encryption import (
    ENCRYPTED_VALUE_PREFIX,
    FieldEncryptionError,
    active_key_id,
    configured_key_ids,
    decrypt_value,
    encrypt_value,
    extract_key_id,
    hmac_sha256_blind_index,
    is_encrypted_value,
    reencrypt_value,
    validate_encryption_configuration,
)
from app.db.base import Base, tenant_id_ctx
from app.db.database import get_db_session
from app.db.tenant_enforcement import enforce_statement, warm_tenant_enforcement_cache
from app.main import create_app
import app.models  # noqa: F401
from app.models.company import Company
from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.manager_repository import ManagerRepository
from app.schemas.manager import ManagerCreate
from app.services.employee_service import EmployeeService
from app.services.manager_service import ManagerService, _employee_sync_filter
from app.core.security import create_access_token


OLD_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
NEW_KEY = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
TABLES = (
    "companies",
    "departments",
    "users",
    "managers",
    "employees",
    "employee_addresses",
    "employee_documents",
    "employee_education",
    "employee_experience",
    "employee_skills",
    "employee_emergency_contacts",
    "employee_bank_accounts",
)


@pytest.fixture
async def iso_session():
    """Isolated async SQLite session for real ORM/repository/service integration tests."""
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"
    if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
        SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(36)"

    selected = [Base.metadata.tables[name] for name in TABLES if name in Base.metadata.tables]
    restored_defaults = []
    for table in selected:
        for column in table.columns:
            if column.server_default is not None:
                arg = str(column.server_default.arg).lower()
                if "jsonb" in arg or "::" in arg or "gen_random_uuid" in arg or "uuid_generate" in arg:
                    restored_defaults.append((column, column.server_default))
                    column.server_default = None

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=selected))
    finally:
        for column, default in restored_defaults:
            column.server_default = default

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _make_employee(company_id: uuid.UUID, *, email: str, emp_code: str, **extra) -> Employee:
    return Employee(
        id=extra.pop("id", uuid.uuid4()),
        company_id=company_id,
        user_id=extra.pop("user_id", None),
        employee_id=emp_code,
        first_name=extra.pop("first_name", "Alex"),
        last_name=extra.pop("last_name", "Ray"),
        personal_email=email,
        company_email=email,
        phone=extra.pop("phone", "9876543210"),
        department=extra.pop("department", "Engineering"),
        designation=extra.pop("designation", "Engineer"),
        joining_date=extra.pop("joining_date", date(2026, 1, 5)),
        **extra,
    )


def _make_manager(company_id: uuid.UUID, *, email: str, mgr_code: str, **extra) -> Manager:
    return Manager(
        id=extra.pop("id", uuid.uuid4()),
        company_id=company_id,
        user_id=extra.pop("user_id", None),
        manager_id=mgr_code,
        first_name=extra.pop("first_name", "Maya"),
        last_name=extra.pop("last_name", "Patel"),
        personal_email=email,
        company_email=email,
        phone=extra.pop("phone", "9876500001"),
        department=extra.pop("department", "Engineering"),
        designation=extra.pop("designation", "Engineering Manager"),
        joining_date=extra.pop("joining_date", date(2026, 1, 5)),
        role="manager",
        status=extra.pop("status", "ACTIVE"),
        is_deleted=extra.pop("is_deleted", False),
        **extra,
    )


# ---------------------------------------------------------------------------
# Phase 2: Field Encryption, Key Rotation & Validation Tests
# ---------------------------------------------------------------------------


def test_encryption_rotation_reencrypt_nullable_and_missing_key(monkeypatch):
    # Encrypt historical value using OLD_KEY
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(OLD_KEY))
    old_id = active_key_id()
    cipher_old = encrypt_value("ABCDE1234F")
    assert is_encrypted_value(cipher_old)
    assert extract_key_id(cipher_old) == old_id

    # Double encryption must not wrap ciphertext twice
    assert encrypt_value(cipher_old) == cipher_old
    assert encrypt_value(None) is None
    assert decrypt_value(None) is None

    # Rotate to NEW_KEY while retaining OLD_KEY: old ciphertexts still decrypt, new writes use NEW_KEY
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(f"{NEW_KEY},{OLD_KEY}"))
    info = validate_encryption_configuration()
    assert info["configured"] is True
    assert len(info["retained_key_ids"]) == 1
    assert old_id in info["retained_key_ids"]
    new_id = active_key_id()
    assert new_id != old_id
    assert decrypt_value(cipher_old) == "ABCDE1234F"

    cipher_new = encrypt_value("ABCDE1234F")
    assert extract_key_id(cipher_new) == new_id
    reencrypted = reencrypt_value(cipher_old)
    assert extract_key_id(reencrypted) == new_id
    assert decrypt_value(reencrypted) == "ABCDE1234F"
    # Idempotent when already encrypted with active key
    assert reencrypt_value(reencrypted) == reencrypted

    # Blind index normalizes consistently across rotation of encryption key and isolates tenants
    comp_1 = uuid.uuid4()
    comp_2 = uuid.uuid4()
    assert hmac_sha256_blind_index("  abcde1234f ", comp_1) == hmac_sha256_blind_index("ABCDE1234F", comp_1)
    assert hmac_sha256_blind_index("ABCDE1234F", comp_1) != hmac_sha256_blind_index("ABCDE1234F", comp_2)

    # Dropping OLD_KEY fails closed with safe key_id fingerprint (never leaks secret or ciphertext)
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(NEW_KEY))
    with pytest.raises(FieldEncryptionError) as exc_info:
        decrypt_value(cipher_old)
    msg = str(exc_info.value)
    assert old_id in msg
    assert OLD_KEY not in msg
    assert NEW_KEY not in msg
    assert "ABCDE1234F" not in msg


def test_encryption_rejects_placeholder_and_empty_production_config(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr("CHANGE_ME_32_BYTE_ENCRYPTION_KEY"))
    with pytest.raises(FieldEncryptionError, match="placeholder"):
        validate_encryption_configuration()

    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(""))
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    with pytest.raises(FieldEncryptionError, match="required"):
        validate_encryption_configuration()

    with pytest.raises(ValidationError, match="FIELD_ENCRYPTION_KEY"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql+asyncpg://user:pass@db.example.com:5432/app",
            JWT_SECRET_KEY="x" * 64,
            FIELD_ENCRYPTION_KEY="CHANGE_ME_32_BYTE_ENCRYPTION_KEY",
        )

    with pytest.raises(ValidationError, match="FIELD_ENCRYPTION_KEY"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql+asyncpg://user:pass@db.example.com:5432/app",
            SECRET_KEY=SecretStr("s" * 64),
            FIELD_ENCRYPTION_KEY="",
        )

    prod_empty = Settings.model_construct(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql+asyncpg://user:pass@db.example.com:5432/app",
        SECRET_KEY=SecretStr("s" * 64),
        JWT_ALGORITHM="RS256",
        REDIS_URL="redis://localhost:6379/0",
        JWT_PRIVATE_KEY=SecretStr("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"),
        JWT_PUBLIC_KEY=SecretStr("-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----"),
        FIELD_ENCRYPTION_KEY=SecretStr(""),
    )
    with pytest.raises(ValueError, match="FIELD_ENCRYPTION_KEY"):
        prod_empty.validate_production_safety()


# ---------------------------------------------------------------------------
# Phase 3 & 4: Duplicate Email & Idempotent Manager Synchronization Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_managers_idempotent_cross_company_conflict_and_soft_delete(iso_session, monkeypatch):
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(NEW_KEY))
    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    iso_session.add_all([
        Company(id=comp_a, name="Comp A"),
        Company(id=comp_b, name="Comp B"),
    ])
    await iso_session.flush()

    # Comp A holds an existing employee with shared personal_email
    shared_email = "sunaina.conflict@example.com"
    emp_a = _make_employee(comp_a, email=shared_email, emp_code="EMP-A-001")
    iso_session.add(emp_a)

    # Comp B has 3 managers:
    # 1) clean missing manager -> should sync cleanly
    # 2) manager conflicting on global personal_email with Comp A -> must skip via savepoint without crashing session
    # 3) manager linked to soft-deleted employee in Comp B -> must not resurrect or fail
    mgr_ok = _make_manager(comp_b, email="clean.mgr@example.com", mgr_code="MGR-B-001")
    mgr_conflict = _make_manager(comp_b, email=shared_email.upper(), mgr_code="MGR-B-002", phone="9876500002")
    mgr_deleted_emp_id = uuid.uuid4()
    mgr_deleted = _make_manager(
        comp_b, id=mgr_deleted_emp_id, email="deleted.emp@example.com", mgr_code="MGR-B-003", phone="9876500003"
    )
    emp_deleted = _make_employee(
        comp_b, id=mgr_deleted_emp_id, email="deleted.emp@example.com", emp_code="MGR-B-003", is_deleted=True, status="DEACTIVATED"
    )
    iso_session.add_all([mgr_ok, mgr_conflict, mgr_deleted, emp_deleted])
    await iso_session.commit()

    service = EmployeeService(
        session=iso_session,
        employee_repository=EmployeeRepository(iso_session),
        auth_repository=AuthRepository(iso_session),
        email_service=AsyncMock(),
    )
    first_stats = await service.sync_managers_to_employees(comp_b)
    assert first_stats == {"created": 1, "updated": 0, "skipped_conflicts": 1}

    # Re-running is completely idempotent (0 created, 0 updated, same clean skip)
    second_stats = await service.sync_managers_to_employees(comp_b)
    assert second_stats == {"created": 0, "updated": 0, "skipped_conflicts": 1}

    # Verify Comp A's employee was never merged/reassigned to Comp B, and mgr_ok exists in Comp B
    await iso_session.refresh(emp_a)
    assert emp_a.company_id == comp_a
    comp_b_emps = (await iso_session.execute(select(Employee).where(Employee.company_id == comp_b))).scalars().all()
    assert {e.personal_email for e in comp_b_emps} == {"clean.mgr@example.com", "deleted.emp@example.com"}


@pytest.mark.asyncio
async def test_create_manager_rejects_global_employee_email_before_insert(iso_session, monkeypatch):
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(NEW_KEY))
    comp_a = uuid.uuid4()
    comp_b = uuid.uuid4()
    admin_b = uuid.uuid4()
    iso_session.add_all([
        Company(id=comp_a, name="Comp A"),
        Company(id=comp_b, name="Comp B"),
        Employee(
            id=uuid.uuid4(),
            company_id=comp_a,
            employee_id="EMP-A-99",
            first_name="Existing",
            last_name="Emp",
            personal_email="dup.global@example.com",
            phone="9000000001",
            department="HR",
            designation="Specialist",
            joining_date=date(2026, 1, 1),
        ),
        User(
            id=admin_b,
            company_id=comp_b,
            name="Admin B",
            email="adminb@example.com",
            phone="9000000002",
            password_hash="x",
            role="hr_admin",
            is_active=True,
            is_verified=True,
        ),
    ])
    await iso_session.commit()

    mgr_svc = ManagerService(
        session=iso_session,
        manager_repository=ManagerRepository(iso_session),
        auth_repository=AuthRepository(iso_session),
        email_service=AsyncMock(),
    )
    payload = ManagerCreate(
        first_name="New",
        last_name="Mgr",
        personal_email="DUP.GLOBAL@example.com",
        phone="9000000099",
        department="Engineering",
        designation="Lead",
        joining_date=date(2026, 2, 1),
    )
    from app.core.exceptions import ConflictException
    with pytest.raises(ConflictException) as exc_info:
        await mgr_svc.create_manager(admin_b, payload)
    assert exc_info.value.field == "personal_email"
    assert exc_info.value.status_code == 409


def test_manager_employee_sync_filter_is_company_scoped():
    mgr = MagicMock(id=uuid.uuid4(), user_id=uuid.uuid4(), company_id=uuid.uuid4(), personal_email="Same@Example.com")
    compiled = str(_employee_sync_filter(Employee, mgr, mgr.id).compile())
    assert "employees.company_id" in compiled
    assert "lower(employees.personal_email)" in compiled


# ---------------------------------------------------------------------------
# Phase 5 & 6: Employee API Projection & Exception Mapping Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_employees_returns_200_with_missing_key_on_unrequested_pii_and_503_on_detail(iso_session, monkeypatch):
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    admin_user = User(
        id=admin_id,
        company_id=company_id,
        name="Acme Admin",
        email="admin@acme.com",
        phone="9000000088",
        password_hash="x",
        role="hr_admin",
        is_active=True,
        is_verified=True,
    )
    iso_session.add(Company(id=company_id, name="Acme Corp"))
    iso_session.add(admin_user)

    # Encrypt historical PAN under OLD_KEY, then switch runtime key to NEW_KEY only
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(OLD_KEY))
    old_id = active_key_id()
    emp = _make_employee(
        company_id,
        email="historical.pii@example.com",
        emp_code="EMP-HIST-01",
        pan_number="ABCDE1234F",
    )
    mgr_only = _make_manager(company_id, email="unlinked.mgr@example.com", mgr_code="MGR-ONLY-01", phone="9111111111")
    iso_session.add_all([emp, mgr_only])
    await iso_session.commit()

    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(NEW_KEY))

    app = create_app()

    async def _override_db():
        yield iso_session

    app.dependency_overrides[get_db_session] = _override_db
    token = create_access_token(
        str(admin_id),
        claims={"role": "hr_admin", "company_id": str(company_id), "email": "admin@acme.com", "is_active": True},
    )

    with patch("app.middleware.auth._check_user_active_cached", new=AsyncMock(return_value=(True, None))):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            list_resp = await client.get("/api/v1/employees", headers={"Authorization": f"Bearer {token}"})
            detail_resp = await client.get(f"/api/v1/employees/{emp.id}", headers={"Authorization": f"Bearer {token}"})

    # List endpoint uses projection (no PII decryption) and performs ZERO writes on GET (does not insert mgr_only)
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["success"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["employee_id"] == "EMP-HIST-01"
    # Verify GET did not create mgr_only in employees table
    count_after_get = (await iso_session.execute(select(Employee).where(Employee.company_id == company_id))).scalars().all()
    assert len(count_after_get) == 1

    # Detail endpoint requires sensitive PII -> must NOT return ciphertext or fake plaintext; returns sanitized 503
    assert detail_resp.status_code == 503
    detail_json = detail_resp.json()
    assert detail_json["success"] is False
    assert detail_json["code"] == "FIELD_ENCRYPTION_UNAVAILABLE"
    assert OLD_KEY not in detail_resp.text
    assert NEW_KEY not in detail_resp.text
    assert old_id not in detail_resp.text
    assert ENCRYPTED_VALUE_PREFIX not in detail_resp.text


@pytest.mark.asyncio
async def test_global_exception_handlers_map_encryption_integrity_and_db_outages():
    from fastapi import FastAPI

    test_app = FastAPI()
    install_exception_handlers(test_app)

    @test_app.get("/err-enc")
    async def err_enc():
        raise FieldEncryptionError("The key required by this encrypted field is not configured (key_id=0eb07e19bb3a).")

    @test_app.get("/err-dup")
    async def err_dup():
        orig = Exception("duplicate key value violates unique constraint ix_employees_personal_email")
        raise IntegrityError("INSERT INTO employees ...", {}, orig)

    @test_app.get("/err-down")
    async def err_down():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    @test_app.get("/err-boom")
    async def err_boom():
        raise RuntimeError("secret-internal-trace")

    async with AsyncClient(transport=ASGITransport(app=test_app, raise_app_exceptions=False), base_url="http://test") as client:
        r_enc = await client.get("/err-enc")
        r_dup = await client.get("/err-dup")
        r_down = await client.get("/err-down")
        r_boom = await client.get("/err-boom")

    assert r_enc.status_code == 503
    assert r_enc.json()["code"] == "FIELD_ENCRYPTION_UNAVAILABLE"
    assert r_dup.status_code == 409
    assert r_dup.json()["code"] == "CONFLICT"
    assert r_down.status_code == 503
    assert r_down.json()["code"] == "DATABASE_UNAVAILABLE"
    assert r_boom.status_code == 500
    assert r_boom.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert "secret-internal-trace" not in r_boom.text


# ---------------------------------------------------------------------------
# Phase 7: Event-Loop Non-Blocking & Tenant Enforcement Speed Tests
# ---------------------------------------------------------------------------


def test_tenant_enforcement_cache_scopes_quickly_without_238_mapper_overhead():
    warmed = warm_tenant_enforcement_cache()
    assert warmed > 10

    tid = uuid.uuid4()
    tok = tenant_id_ctx.set(tid)
    try:
        from types import SimpleNamespace
        t0 = time.perf_counter()
        for _ in range(50):
            st = SimpleNamespace(
                statement=select(Employee.id, Employee.first_name),
                parameters=None,
                execution_options={},
                is_select=True,
                is_update=False,
                is_delete=False,
            )
            enforce_statement(st)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        tenant_id_ctx.reset(tok)

    # 50 attaches should complete comfortably well under 250ms (<5ms/query) vs old ~1000ms
    assert elapsed_ms < 250.0, f"enforce_statement too slow: {elapsed_ms:.1f}ms for 50 calls"


def test_no_sync_bcrypt_calls_inside_async_endpoints_or_services():
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for folder in (root / "app" / "api", root / "app" / "services"):
        for py_file in folder.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            fn = child.func
                            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                            if name in {"hash_password", "verify_password"}:
                                violations.append(f"{py_file.relative_to(root)}:{child.lineno}:{name}")
    assert not violations, f"Blocking sync bcrypt calls found inside async def: {violations}"
