"""Feature #22 / E2: DPDP compliance and sensitive-data security tests."""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from datetime import date, datetime, timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.field_encryption import (
    ENCRYPTED_VALUE_PREFIX,
    decrypt_value,
    encrypt_value,
    hmac_sha256_blind_index,
)
from app.core.structured_logging import PIIRedactionFilter
from app.db.base import Base
import app.models  # noqa: F401 - register the complete model metadata
from app.models.audit_log import AuditLog, PII_UNMASK_ACCESS
from app.models.dpdp_compliance import ConsentStatus, DataSubjectRequestStatus
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.leave import LeaveRequest
from app.models.payroll import Payslip
from app.attendance.models.attendance import Attendance
from app.schemas.employee.bank import BankAccountResponse
from app.schemas.employee.profile import EmployeeResponse
from app.services.dpdp_service import DPDPNotFoundError, DPDPService
from scripts.backfill_encrypted_pii import backfill_encrypted_pii


TEST_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
ROTATED_KEY = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
TEST_TABLES = (
    "employees",
    "employee_addresses",
    "employee_documents",
    "employee_education",
    "employee_experience",
    "employee_skills",
    "employee_emergency_contacts",
    "employee_bank_accounts",
    "attendances",
    "leave_requests",
    "payslips",
    "data_consent_ledger",
    "data_retention_policies",
    "data_subject_requests",
    "audit_logs",
)


@pytest.fixture(autouse=True)
def field_key(monkeypatch):
    monkeypatch.setattr(settings, "FIELD_ENCRYPTION_KEY", SecretStr(TEST_KEY))


@pytest.fixture
async def db_session():
    """Create the relevant real tables in SQLite with PostgreSQL type shims."""

    # Production uses PostgreSQL JSONB/UUID. SQLite can execute these particular
    # tables once JSONB is rendered as JSON; PostgreSQL-only jsonb defaults are
    # restored immediately after CREATE TABLE.
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"
    selected = [Base.metadata.tables[name] for name in TEST_TABLES]
    defaults = []
    for table in selected:
        for column in table.columns:
            if column.server_default and "jsonb" in str(column.server_default.arg).lower():
                defaults.append((column, column.server_default))
                column.server_default = None

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=selected))
    finally:
        for column, default in defaults:
            column.server_default = default

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _employee(company_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> Employee:
    return Employee(
        id=uuid.uuid4(),
        company_id=company_id,
        user_id=user_id,
        employee_id=f"EMP-{uuid.uuid4().hex[:8]}",
        first_name="Asha",
        last_name="Sharma",
        personal_email=f"asha-{uuid.uuid4().hex[:8]}@example.com",
        phone="9876543210",
        department="Engineering",
        designation="Engineer",
        joining_date=date(2024, 1, 10),
        aadhaar_number="123456789012",
        pan_number="ABCDE1234F",
        uan_number="101234567890",
        passport_number="A1234567",
        voter_id="ABC1234567",
    )


def _payslip(employee: Employee, *, net_pay: str = "75000") -> Payslip:
    return Payslip(
        id=uuid.uuid4(),
        company_id=employee.company_id,
        payroll_run_id=uuid.uuid4(),
        employee_id=employee.id,
        payslip_number=f"PAY-{uuid.uuid4().hex[:12]}",
        period_month=10,
        period_year=2026,
        total_days_in_month=31,
        paid_days=31,
        lop_days=0,
        gross_earnings="100000",
        employee_pf="1800",
        total_deductions="25000",
        net_pay=net_pay,
    )


async def _persist_employee(session, employee: Employee) -> Employee:
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return employee


@pytest.mark.asyncio
async def test_encryption_at_rest_blind_index_and_backfill_are_idempotent(db_session):
    company_id = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_id))
    account = EmployeeBankAccount(
        employee_id=employee.id,
        bank_name="HDFC",
        account_number="12345678901234",
        ifsc_code="HDFC0001234",
    )
    db_session.add(account)
    await db_session.commit()

    raw = (
        await db_session.execute(
            text(
                "SELECT pan_number, aadhaar_number, pan_number_blind_idx "
                "FROM employees WHERE id = :id"
            ),
            {"id": employee.id.hex},
        )
    ).mappings().one()
    assert raw["pan_number"].startswith(ENCRYPTED_VALUE_PREFIX)
    assert raw["aadhaar_number"].startswith(ENCRYPTED_VALUE_PREFIX)
    assert "ABCDE1234F" not in raw["pan_number"]
    assert decrypt_value(raw["pan_number"]) == "ABCDE1234F"
    assert raw["pan_number_blind_idx"] == hmac_sha256_blind_index("ABCDE1234F", company_id)

    raw_bank = (
        await db_session.execute(
            text("SELECT account_number, ifsc_code FROM employee_bank_accounts WHERE employee_id = :id"),
            {"id": employee.id.hex},
        )
    ).mappings().one()
    assert decrypt_value(raw_bank["account_number"]) == "12345678901234"
    assert decrypt_value(raw_bank["ifsc_code"]) == "HDFC0001234"
    assert raw_bank["account_number"] != "12345678901234"

    # Simulate a pre-migration plaintext row, then run the management helper.
    await db_session.execute(
        text("UPDATE employees SET pan_number = :plain, pan_number_blind_idx = NULL WHERE id = :id"),
        {"plain": "ABCDE1234F", "id": employee.id.hex},
    )
    await db_session.execute(
        text("UPDATE employee_bank_accounts SET account_number = :plain WHERE employee_id = :id"),
        {"plain": "12345678901234", "id": employee.id.hex},
    )
    await db_session.commit()
    first = await backfill_encrypted_pii(db_session, batch_size=1)
    assert first["employees_encrypted"] >= 1
    assert first["bank_values_encrypted"] >= 1
    second = await backfill_encrypted_pii(db_session, batch_size=1)
    assert second["employees_encrypted"] == 0
    assert second["bank_values_encrypted"] == 0
    assert second["employee_indexes_updated"] == 0


def test_key_rotation_and_tenant_bound_blind_indexes(monkeypatch):
    old_ciphertext = encrypt_value("ABCDE1234F")
    monkeypatch.setattr(
        settings,
        "FIELD_ENCRYPTION_KEY",
        SecretStr(f"{ROTATED_KEY},{TEST_KEY}"),
    )
    assert decrypt_value(old_ciphertext) == "ABCDE1234F"
    new_ciphertext = encrypt_value("ABCDE1234F")
    assert new_ciphertext != old_ciphertext
    assert decrypt_value(new_ciphertext) == "ABCDE1234F"

    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    assert hmac_sha256_blind_index(" abcde-1234f ", company_a) == hmac_sha256_blind_index(
        "ABCDE1234F", company_a
    )
    assert hmac_sha256_blind_index("ABCDE1234F", company_a) != hmac_sha256_blind_index(
        "ABCDE1234F", company_b
    )


@pytest.mark.asyncio
async def test_standard_serializers_mask_or_redact_sensitive_identifiers(db_session):
    employee = await _persist_employee(db_session, _employee(uuid.uuid4()))
    account = EmployeeBankAccount(
        id=uuid.uuid4(),
        employee_id=employee.id,
        bank_name="HDFC",
        account_holder_name="Asha Sharma",
        account_number="12345678901234",
        ifsc_code="HDFC0001234",
        account_type="SAVINGS",
        is_primary=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    bank_response = BankAccountResponse.model_validate(account)
    assert bank_response.account_number == "XXXXXXXXXX1234"
    assert "12345678901234" not in bank_response.model_dump_json()

    values = {column.key: getattr(employee, column.key) for column in Employee.__table__.columns}
    response = EmployeeResponse.model_validate(values)
    assert response.pan_number == "ABCDE****F"
    assert response.uan_number == "********7890"
    assert response.aadhaar_number == "[REDACTED]"
    assert response.passport_number == "[REDACTED]"
    assert response.voter_id == "[REDACTED]"
    serialized = response.model_dump_json()
    for raw in ("123456789012", "ABCDE1234F", "101234567890", "A1234567", "ABC1234567"):
        assert raw not in serialized


def test_pii_log_redaction_covers_keys_and_freeform_values():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(PIIRedactionFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(f"dpdp-test-{uuid.uuid4()}")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info(
            "payload=%s",
            {"pan_number": "ABCDE1234F", "account_number": "12345678901234"},
        )
        logger.info("aadhaar=1234 5678 9012 passport=A1234567")
        logger.info("pan_number=%s", "ABCDE1234F")
        logger.info("account_number=%s", "12345")
        logger.info("context", extra={"uan_number": "101234567890"})
        output = stream.getvalue()
    finally:
        logger.removeHandler(handler)

    for raw in ("ABCDE1234F", "12345678901234", "12345", "1234 5678 9012", "A1234567"):
        assert raw not in output
    assert "[MASKED" in output


@pytest.mark.asyncio
async def test_consent_ledger_grant_withdraw_and_me_query(db_session):
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_id, user_id=user_id))
    service = DPDPService(db_session)
    granted = await service.record_consent(
        employee_id=employee.id,
        company_id=company_id,
        user_id=user_id,
        purpose_code="PAYROLL_PROCESSING",
        policy_version="2026-10-v1",
        consent_status="GRANTED",
        ip_address="127.0.0.1",
    )
    withdrawn = await service.record_consent(
        employee_id=employee.id,
        company_id=company_id,
        user_id=user_id,
        purpose_code="PAYROLL_PROCESSING",
        policy_version="2026-10-v1",
        consent_status="WITHDRAWN",
    )
    assert granted.granted_at is not None
    assert withdrawn.withdrawn_at is not None

    entries = await service.list_consents_for_user(user_id=user_id, company_id=company_id)
    assert len(entries) == 2
    assert {entry.consent_status for entry in entries} == {
        ConsentStatus.GRANTED.value,
        ConsentStatus.WITHDRAWN.value,
    }
    assert all(entry.company_id == company_id for entry in entries)


@pytest.mark.asyncio
async def test_data_export_contains_all_sections_and_valid_zip(db_session):
    company_id = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_id))
    db_session.add(
        Attendance(
            employee_id=employee.id,
            company_id=company_id,
            date=date(2026, 10, 26),
            status="Present",
        )
    )
    db_session.add(
        LeaveRequest(
            employee_id=employee.id,
            leave_type="Casual",
            start_date=date(2026, 10, 20),
            end_date=date(2026, 10, 20),
            total_days=1,
            reason="Personal",
        )
    )
    db_session.add(_payslip(employee))
    await db_session.commit()

    service = DPDPService(db_session)
    payload = await service.export_employee_data(
        employee_id=employee.id, company_id=company_id, actor_id=uuid.uuid4()
    )
    assert set(("personal", "attendance", "leave", "payslips", "manifest")) <= set(payload)
    assert payload["personal"]["pan_number"] == "ABCDE1234F"
    assert len(payload["attendance"]) == 1
    assert len(payload["leave"]) == 1
    assert float(payload["payslips"][0]["net_pay"]) == 75000
    assert payload["manifest"]["data_subject_request_id"]

    archive_bytes = service.export_as_zip(payload)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert {"personal.json", "attendance.json", "leave.json", "payslips.json"} <= set(
            archive.namelist()
        )
        exported = json.loads(archive.read("dpdp-export.json"))
        assert exported["manifest"]["employee_id"] == str(employee.id)
    assert json.loads(service.export_as_json(payload))["personal"]["employee_id"] == employee.employee_id


@pytest.mark.asyncio
async def test_erasure_is_rejected_during_statutory_hold(db_session):
    company_id = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_id))
    original_email = employee.personal_email
    payslip = _payslip(employee)
    db_session.add(payslip)
    await db_session.commit()
    service = DPDPService(db_session)
    data_request = await service.create_erasure_request(employee_id=employee.id, company_id=company_id)

    result = await service.execute_erasure_request(
        request_id=data_request.id, company_id=company_id, reviewer_id=uuid.uuid4()
    )
    assert result.status == DataSubjectRequestStatus.REJECTED_STATUTORY_HOLD.value
    assert employee.personal_email == original_email
    assert float(payslip.net_pay) == 75000
    summary = json.loads(result.execution_summary)
    assert summary["held_record_count"] == 1
    assert summary["retention_days"] == 2920


@pytest.mark.asyncio
async def test_erasure_anonymises_pii_and_preserves_statutory_totals_after_retention(db_session):
    company_id = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_id))
    account = EmployeeBankAccount(
        employee_id=employee.id,
        bank_name="HDFC",
        account_number="12345678901234",
        ifsc_code="HDFC0001234",
    )
    payslip = _payslip(employee, net_pay="81234")
    db_session.add_all([account, payslip])
    await db_session.commit()
    service = DPDPService(db_session)
    await service.set_retention_policy(
        company_id=company_id, entity_type="PAYROLL", retention_days=0
    )
    data_request = await service.create_erasure_request(employee_id=employee.id, company_id=company_id)
    result = await service.execute_erasure_request(
        request_id=data_request.id, company_id=company_id, reviewer_id=uuid.uuid4()
    )

    assert result.status == DataSubjectRequestStatus.EXECUTED.value
    assert employee.first_name == "Erased"
    assert employee.personal_email.endswith("@erased.invalid")
    assert employee.aadhaar_number is None
    assert employee.pan_number == "ABCDE1234F"  # statutory identity is retained with old ledgers
    assert account.account_number.startswith("ERASED-")
    assert float(payslip.net_pay) == 81234
    summary = json.loads(result.execution_summary)
    assert summary["payslip_records_preserved"] == 1
    assert float(summary["net_pay_preserved"]) == 81234


@pytest.mark.asyncio
async def test_cross_tenant_ids_are_not_found(db_session):
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_a))
    service = DPDPService(db_session)
    data_request = await service.create_erasure_request(employee_id=employee.id, company_id=company_a)

    with pytest.raises(DPDPNotFoundError):
        await service.get_employee(employee.id, company_b)
    with pytest.raises(DPDPNotFoundError):
        await service.record_consent(
            employee_id=employee.id,
            company_id=company_b,
            user_id=None,
            purpose_code="TAX_FILING",
            policy_version="v1",
        )
    with pytest.raises(DPDPNotFoundError):
        await service.execute_erasure_request(
            request_id=data_request.id, company_id=company_b, reviewer_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_dpdp_http_routes_support_self_service_export_and_requests(db_session):
    from fastapi import FastAPI
    from app.api.v2.router import get_v2_router
    from app.db.database import get_db_session
    from app.middleware.auth import get_current_user_claims

    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await _persist_employee(db_session, _employee(company_id, user_id=user_id))
    claims = {"sub": str(user_id), "role": "EMPLOYEE", "company_id": str(company_id)}
    app = FastAPI()
    app.include_router(get_v2_router())

    async def override_claims():
        return claims

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user_claims] = override_claims
    app.dependency_overrides[get_db_session] = override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        consent = await client.post(
            "/api/v2/dpdp/consents",
            json={"purpose_code": "PAYROLL_PROCESSING", "policy_version": "v1"},
        )
        assert consent.status_code == 201, consent.text
        mine = await client.get("/api/v2/dpdp/consents/me")
        assert mine.status_code == 200
        assert len(mine.json()["data"]) == 1

        # An omitted body is valid for a self-service export and erasure request.
        exported = await client.post("/api/v2/dpdp/data-export")
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert "personal.json" in archive.namelist()
        json_export = await client.post("/api/v2/dpdp/data-export", json={"format": "json"})
        assert json_export.status_code == 200, json_export.text
        assert json_export.json()["personal"]["pan_number"] == "ABCDE1234F"
        erasure = await client.post("/api/v2/dpdp/erasure-requests")
        assert erasure.status_code == 201, erasure.text
        assert erasure.json()["data"]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_sensitive_pii_endpoint_is_audited_and_cross_tenant_returns_404(db_session):
    from fastapi import FastAPI
    from app.api.v2.router import get_v2_router
    from app.db.database import get_db_session
    from app.middleware.auth import get_current_user_claims

    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    employee = await _persist_employee(db_session, _employee(company_a))
    db_session.add(
        EmployeeBankAccount(
            employee_id=employee.id,
            bank_name="HDFC",
            account_number="12345678901234",
            ifsc_code="HDFC0001234",
        )
    )
    await db_session.commit()
    claims = {
        "sub": str(uuid.uuid4()),
        "role": "hr_admin",
        "company_id": str(company_a),
        "email": "hr@example.com",
    }

    app = FastAPI()
    # Exercise the real v2 assembly so route-mount regressions are caught too.
    app.include_router(get_v2_router())

    async def override_claims():
        return claims

    async def override_db():
        yield db_session

    app.dependency_overrides[get_current_user_claims] = override_claims
    app.dependency_overrides[get_db_session] = override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v2/employees/{employee.id}/sensitive-pii")
        assert response.status_code == 200
        assert response.json()["data"]["pan_number"] == "ABCDE1234F"
        assert response.json()["data"]["bank_accounts"][0]["account_number"] == "12345678901234"

        claims["role"] = "EMPLOYEE"
        forbidden = await client.get(f"/api/v2/employees/{employee.id}/sensitive-pii")
        assert forbidden.status_code == 403
        claims["role"] = "hr_admin"
        claims["company_id"] = str(company_b)
        foreign = await client.get(f"/api/v2/employees/{employee.id}/sensitive-pii")
        assert foreign.status_code == 404
        foreign_consent = await client.post(
            "/api/v2/dpdp/consents",
            json={
                "employee_id": str(employee.id),
                "purpose_code": "TAX_FILING",
                "policy_version": "v1",
                "consent_status": "GRANTED",
            },
        )
        assert foreign_consent.status_code == 404

    from sqlalchemy import select

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == PII_UNMASK_ACCESS).execution_options(
                bypass_tenant=True
            )
        )
    ).scalars().all()
    assert len(audit_rows) == 1
    assert audit_rows[0].entity_id == str(employee.id)
    assert "ABCDE1234F" not in (audit_rows[0].details or "")
    assert "ABCDE1234F" not in (audit_rows[0].metadata_json or "")

    audit_rows[0].details = "attempted tampering"
    with pytest.raises(ValueError, match="immutable"):
        await db_session.flush()
    await db_session.rollback()
