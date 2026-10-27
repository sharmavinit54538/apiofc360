"""Batch 4 focused service/integration tests (SQLite; no demo seed data)."""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from app.db.base import Base
import app.models  # noqa: F401 - register metadata
from app.models.company import Branch, Company, LegalEntity
from app.models.data_migration import DataMigrationBatch, DataMigrationRecord
from app.models.department import Department
from app.models.document import DocumentTemplate
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.employee_onboarding import EmployeeOnboarding, OnboardingTaskChecklist
from app.models.exit import AssetReturn, ClearanceRequest, EmployeeExit, ExitDocument, FnfSettlement
from app.models.leave_balance import LeaveBalance
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_models import EmployeeYTDSalary, FullAndFinalSettlement
from app.models.recruitment import Application, Job, Offer
from app.models.user import User
from app.services.data_migration_service import DataMigrationService
from app.services.document_templates import CANONICAL_TEMPLATES
from app.services.employee_bulk_service import EmployeeBulkService
from app.services.employee_onboarding_service import EmployeeOnboardingService
from app.services.esign_service import ESignService
from app.services.fnf_calculation_service import FnfCalculationService
from app.services.fnf_workflow_service import FnFWorkflowService
from app.services.letter_service import CANONICAL_LETTER_NAMES, LetterService
from app.services.payroll.full_and_final_service import FullAndFinalService
from app.services.payroll.payslip_service import PayslipService


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kwargs):
    return "JSON"


TEST_TABLES = [
    "companies", "users", "legal_entities", "branches", "departments", "employees",
    "jobs", "candidates", "applications", "offers", "employee_onboarding",
    "onboarding_task_checklists", "document_templates", "employee_documents",
    "document_versions", "document_signatures", "document_audit_logs",
    "employee_exits", "asset_returns", "clearance_requests", "fnf_settlements",
    "exit_documents", "assets", "leave_balances", "data_migration_batches",
    "data_migration_records", "employee_ytd_salaries", "payroll_runs", "payslips",
    "payroll_run_employees", "full_and_final_settlements", "payroll_audit_logs",
]


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    for module_name in (
        "app.services.storage_service", "app.services.letter_service", "app.services.esign_service",
    ):
        module = __import__(module_name, fromlist=["DOCUMENTS_DIR_ABSOLUTE"])
        monkeypatch.setattr(module, "DOCUMENTS_DIR_ABSOLUTE", str(tmp_path / "documents"))
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [Base.metadata.tables[name] for name in TEST_TABLES]
    # The production schema is PostgreSQL.  Strip only server-side JSONB cast
    # syntax while compiling the same table metadata for focused SQLite tests.
    import re
    from sqlalchemy import text
    default_restore = []
    index_restore = []
    for table in tables:
        seen_indexes = set()
        for index in list(table.indexes):
            if index.name in seen_indexes:
                table.indexes.remove(index)
                index_restore.append((table, index))
            else:
                seen_indexes.add(index.name)
        for column in table.columns:
            default = column.server_default
            if default is not None and hasattr(default, "arg") and "::jsonb" in str(default.arg):
                default_restore.append((default, default.arg))
                default.arg = text(re.sub(r"::jsonb", "", str(default.arg)))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
    finally:
        for default, original in default_restore:
            default.arg = original
        for table, index in index_restore:
            table.indexes.add(index)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _company(db: AsyncSession) -> Company:
    company = Company(id=uuid.uuid4(), name="Batch 4 Test Pvt Ltd")
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company, prefix: str = "signer") -> User:
    unique = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(), company_id=company.id, name=f"{prefix.title()} User",
        email=f"{prefix}-{unique}@example.com", phone=str(int(unique[:8], 16))[:10].ljust(10, "1"),
        password_hash="test-only-hash", role="employee", is_active=True, is_verified=True,
        account_status="ACTIVE",
    )
    db.add(user)
    await db.flush()
    return user


async def _employee(db: AsyncSession, company: Company, user: User | None = None, code: str | None = None) -> Employee:
    unique = uuid.uuid4().hex[:8]
    employee = Employee(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id if user else None,
        employee_id=code or f"EMP-{unique}", first_name="Real", last_name="Employee",
        personal_email=f"employee-{unique}@example.com", phone="9876543210",
        department="Engineering", designation="Engineer", joining_date=date(2020, 1, 1),
        employment_type="FULL_TIME", employment_status="CONFIRMED", status="ACTIVE", role="employee",
    )
    db.add(employee)
    await db.flush()
    return employee


def _seed_letters(db: AsyncSession, names=CANONICAL_LETTER_NAMES):
    for item in CANONICAL_TEMPLATES:
        if item["name"] in names:
            db.add(DocumentTemplate(id=uuid.uuid4(), name=item["name"], description=item["description"], template_body=item["template_body"]))


@pytest.mark.asyncio
async def test_offer_preboarding_is_idempotent_and_tracks_bgv_checklist(db, monkeypatch):
    async def sqlite_test_employee_id(session):
        return f"EMP-{uuid.uuid4().hex[:10].upper()}"
    monkeypatch.setattr("app.services.employee_service.generate_employee_id", sqlite_test_employee_id)
    company = await _company(db)
    job = Job(
        id=uuid.uuid4(), company_id=company.id, title="Platform Engineer", slug=f"platform-{uuid.uuid4().hex}",
        department="Engineering", designation="Engineer", location="Jaipur", job_description="Real role",
    )
    application = Application(
        id=uuid.uuid4(), company_id=company.id, job=job, first_name="New", last_name="Joiner",
        email="new.joiner@example.com", phone="9876543210", country="India", state="Rajasthan", city="Jaipur",
    )
    offer = Offer(
        id=uuid.uuid4(), company_id=company.id, application=application, ctc=Decimal("1200000"),
        joining_date=date.today() + timedelta(days=30), offer_expiry_date=date.today() + timedelta(days=7), status="ACCEPTED",
    )
    db.add_all([job, application, offer])
    await db.flush()
    service = EmployeeOnboardingService(db)
    employee = await service.create_preboarding_from_offer(offer.id)
    token = employee._onboarding_invite_token
    await db.commit()
    repeated = await service.create_preboarding_from_offer(offer.id)
    assert repeated.id == employee.id
    assert repeated._preboarding_created is False
    assert employee.status == "PREBOARDING"
    steps = (await db.execute(select(EmployeeOnboarding).where(EmployeeOnboarding.employee_id == employee.id))).scalars().all()
    assert len(steps) == 10
    assert all(step.invite_token_hash and step.invite_token_hash != token for step in steps)
    tasks = (await db.execute(select(OnboardingTaskChecklist).where(OnboardingTaskChecklist.employee_id == employee.id))).scalars().all()
    assert {task.category for task in tasks} == {"IT", "ADMIN", "HR"}
    assert len(tasks) == 6
    await service.update_bgv_status(employee.id, "VERIFIED_CLEAR", provider_reference="bgv-real-1")
    for task in tasks[:3]:
        await service.complete_provisioning_task(employee.id, task.id)
    checklist = await service.get_joining_checklist(employee.id)
    assert checklist["completion_percentage"] == 50.0
    with pytest.raises(ValueError):
        await service.update_bgv_status(employee.id, "INVALID")


@pytest.mark.asyncio
async def test_ocr_rules_mask_sensitive_values(db):
    service = EmployeeOnboardingService(db)
    pan = service.validate_onboarding_document("PAN", {"pan_number": "ABCDE1234F", "confidence": 0.98})
    government = service.validate_onboarding_document("AADHAAR", {"aadhaar_number": "1234 5678 9012"})
    bank = service.validate_onboarding_document("CANCELLED_CHEQUE", {"account_number": "123456789012", "ifsc_code": "HDFC0001234"})
    uan = service.validate_onboarding_document("UAN", {"uan_number": "123456789012"})
    assert all(result["valid"] for result in (pan, government, bank, uan))
    assert government["normalized"]["masked_government_id"] == "XXXX-XXXX-9012"
    assert "123456789012" not in str(government["normalized"])
    assert bank["normalized"]["bank_account_masked"] == "XXXXXX9012"
    assert not service.validate_onboarding_document("UAN", {"uan_number": "ABC123"})["valid"]
    # Document AI commonly returns text only; all required proof types must be
    # parseable without trusting a client-supplied structured field.
    assert service.validate_onboarding_document("AADHAAR", {"text": "Aadhaar: 1234 5678 9012"})["valid"]
    assert service.validate_onboarding_document("CANCELLED_CHEQUE", {"text": "Account Number: 1234 5678 9012\nIFSC: HDFC0001234"})["valid"]
    assert service.validate_onboarding_document("UAN", {"text": "UAN: 1234 5678 9012"})["valid"]
    assert not service.validate_onboarding_document("PAN", {"pan_number": "ABCDE1234F", "confidence": "unknown"})["valid"]


@pytest.mark.asyncio
async def test_tenant_bulk_dry_run_import_export_and_mapping(db):
    company = await _company(db)
    other_company = await _company(db)
    legal = LegalEntity(id=uuid.uuid4(), company_id=company.id, name="Batch 4 Legal", code="B4L", gstin="08ABCDE1234F1Z5")
    other_legal = LegalEntity(id=uuid.uuid4(), company_id=other_company.id, name="Other Legal", code="OTHER")
    db.add_all([legal, other_legal])
    await db.flush()
    branch = Branch(id=uuid.uuid4(), company_id=company.id, legal_entity_id=legal.id, name="Jaipur", code="JPR")
    other_branch = Branch(id=uuid.uuid4(), company_id=other_company.id, legal_entity_id=other_legal.id, name="Other", code="OTH")
    db.add_all([branch, other_branch])
    await db.flush()
    department = Department(
        id=uuid.uuid4(), company_id=company.id, branch_id=branch.id, department_code="ENG",
        department_name="Engineering", normalized_code="ENG", location="Jaipur",
    )
    db.add(department)
    await db.flush()
    rows = [
        {"employee_id": "MGR-1", "first_name": "Manager", "personal_email": "mgr1@example.com", "phone": "9876543210", "department_code": "ENG", "designation": "Manager", "joining_date": "2026-01-01", "branch_code": "JPR"},
        {"employee_id": "EMP-1", "first_name": "Staff", "personal_email": "staff1@example.com", "phone": "9876543211", "department_code": "ENG", "designation": "Engineer", "joining_date": "2026-01-02", "branch_code": "JPR", "reporting_manager_code": "MGR-1"},
    ]
    import csv, io
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=sorted({key for row in rows for key in row}))
    writer.writeheader()
    writer.writerows(rows)
    content = output.getvalue().encode()
    service = EmployeeBulkService(db)
    dry = await service.import_employees(company.id, content, "employees.csv", dry_run=True)
    assert dry["imported_count"] == 0 and dry["valid_rows"] == 2 and not dry["errors"]
    assert (await db.execute(select(Employee))).scalars().all() == []
    committed = await service.import_employees(company.id, content, "employees.csv")
    assert committed["imported_count"] == 2
    employees = (await db.execute(select(Employee))).scalars().all()
    assert len(employees) == 2
    staff = next(employee for employee in employees if employee.employee_id == "EMP-1")
    manager = next(employee for employee in employees if employee.employee_id == "MGR-1")
    assert staff.reporting_manager_id == manager.id
    assert staff.branch_id == branch.id and staff.legal_entity_id == legal.id
    exported, filename, media_type = await service.export_employees(company.id, "csv")
    assert filename == "employees.csv" and b"EMP-1" in exported and "text/csv" in media_type
    invalid = [dict(rows[0], employee_id="BAD-1", personal_email="bad1@example.com", branch_id=str(other_branch.id), branch_code="")]
    valid, errors = await service.validate_employees(company.id, invalid)
    assert not valid and errors


@pytest.mark.asyncio
async def test_all_letters_pdf_and_signature_pad_audit(db):
    company = await _company(db)
    signer = await _user(db, company)
    employee = await _employee(db, company, signer)
    _seed_letters(db)
    await db.flush()
    letters = LetterService(db)
    for letter_type in CANONICAL_LETTER_NAMES:
        rendered = await letters.render_letter(letter_type, employee.id, company_id=company.id)
        assert rendered["pdf_bytes"].startswith(b"%PDF")
        assert "Real Employee" in rendered["content"]
        assert "Batch 4 Test Pvt Ltd" in rendered["content"]
    generated = await letters.generate_letter("APPOINTMENT", employee.id, company_id=company.id, actor_id=signer.id)
    document = await db.get(EmployeeDocument, uuid.UUID(generated["document_id"]))
    esign = ESignService(db)
    request = await esign.request_esign(
        document.id, signer.id, requested_by=signer.id, company_id=company.id,
        method="SIGNATURE_PAD", request_ip="203.0.113.10", user_agent="Batch4-Test",
    )
    assert request["otp"] is None
    signed = await esign.sign_document(
        document.id, signer.id, signature_data="data:image/png;base64,aGVsbG8=",
        signer_ip="203.0.113.11", user_agent="SignaturePad/1.0", device_info="test-pad",
    )
    assert signed["status"] == "SIGNED"
    assert signed["signed_pdf_hash"] and signed["signed_pdf_hash"] != signed["document_hash"]
    certificate, certificate_pdf = await esign.get_audit_certificate(document.id, company_id=company.id)
    assert certificate["signer_ip"] == "203.0.113.11"
    assert certificate["user_agent"] == "SignaturePad/1.0"
    assert certificate["signed_pdf_intact"] is True
    assert certificate_pdf.startswith(b"%PDF")
    with pytest.raises(PermissionError):
        await esign.process_provider_webhook("DOCUSIGN", {}, raw_body=b"{}", webhook_secret=None)


@pytest.mark.asyncio
async def test_fnf_clearance_settlement_sheet_and_payroll_settled_transition(db):
    company = await _company(db)
    actor = await _user(db, company, "payroll")
    employee = await _employee(db, company, actor)
    _seed_letters(db, {"Relieving Letter", "Experience Letter"})
    exit_obj = EmployeeExit(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id, reason="Resignation",
        personal_email=employee.personal_email, personal_phone=employee.phone,
        last_working_date=date(2026, 10, 31), status="NOTICE_PERIOD",
        notice_period_days_required=30, notice_period_days_served=30,
    )
    db.add(exit_obj)
    await db.flush()
    asset = AssetReturn(id=uuid.uuid4(), exit_id=exit_obj.id, asset_name="Laptop", return_status="PENDING")
    clearance = ClearanceRequest(
        id=uuid.uuid4(), exit_id=exit_obj.id, it_clearance=True, hr_clearance=True,
        finance_clearance=True, admin_clearance=True, manager_clearance=True,
        security_clearance=True, overall_status="CLEARED",
    )
    fnf = FnfSettlement(
        id=uuid.uuid4(), exit_id=exit_obj.id, status="FINALIZED", payment_status="PAID",
        pending_salary=Decimal("50000"), net_payable_amount=Decimal("50000"),
        settlement_breakup={"pending_salary": 50000, "net_payable_amount": 50000},
    )
    db.add_all([asset, clearance, fnf])
    await db.flush()
    workflow = FnFWorkflowService(db)
    with pytest.raises(ValueError, match="100%"):
        await workflow.assert_clearances(exit_obj.id)
    asset.return_status = "RETURNED"
    await db.flush()
    assert (await workflow.assert_clearances(exit_obj.id))["clearance_complete"] is True
    settled = await workflow.settle_exit_fnf(exit_obj.id, actor_id=actor.id)
    assert settled.status == "SETTLED" and settled.settled_at is not None
    assert exit_obj.status == "SETTLED"
    assert settled.statement_path and open(settled.statement_path, "rb").read(4) == b"%PDF"
    exit_documents = (await db.execute(select(ExitDocument).where(ExitDocument.exit_id == exit_obj.id))).scalars().all()
    assert {document.document_type for document in exit_documents} == {"RELIEVING_LETTER", "EXPERIENCE_LETTER"}
    # Existing payroll finalization remains FINALIZED; settlement is a separate transition.
    payroll_fnf = FullAndFinalSettlement(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id, exit_id=exit_obj.id,
        resignation_date=date(2026, 10, 1), last_working_date=exit_obj.last_working_date,
        exit_type="resignation", reason="Resignation", status="APPROVED",
        net_payable_paise=5_000_000, settlement_breakup={"net_payable_paise": 5_000_000},
    )
    db.add(payroll_fnf)
    await db.flush()
    finalized = await FullAndFinalService.finalize_settlement(db, payroll_fnf.id, user_id=actor.id, user_role="hr_admin")
    assert finalized.status == "FINALIZED"
    legacy_statement, legacy_filename = await FullAndFinalService.generate_statement(db, payroll_fnf.id)
    assert legacy_filename.endswith(".txt") and b"FULL & FINAL SETTLEMENT STATEMENT" in legacy_statement
    payroll_settled = await workflow.settle_payroll_fnf(payroll_fnf.id, actor_id=actor.id, actor_role="hr_admin")
    assert payroll_settled.status == "SETTLED"
    assert payroll_settled.settlement_sheet_hash


@pytest.mark.asyncio
async def test_employee_and_opening_leave_migration_rollback(db):
    company = await _company(db)
    actor = await _user(db, company, "migration")
    service = DataMigrationService(db)
    employee_rows = [
        {"employee_id": "MIG-MGR", "first_name": "Migration", "last_name": "Manager", "personal_email": "mig-mgr@example.com", "phone": "9876543210", "department": "Operations", "designation": "Manager", "joining_date": "2025-01-01"},
        {"employee_id": "MIG-EMP", "first_name": "Migration", "last_name": "Staff", "personal_email": "mig-emp@example.com", "phone": "9876543211", "department": "Operations", "designation": "Staff", "joining_date": "2025-01-02", "reporting_manager_code": "MIG-MGR"},
    ]
    employee_batch = await service.validate_payload(company_id=company.id, migration_type="EMPLOYEE_MASTER", rows=employee_rows, actor_id=actor.id)
    assert employee_batch.status == "VALIDATED"
    await service.commit_batch(employee_batch.id, company_id=company.id)
    assert (await db.execute(select(DataMigrationRecord).where(DataMigrationRecord.batch_id == employee_batch.id))).scalars().all()
    await service.rollback_batch(employee_batch.id, company_id=company.id, reason="Test rollback")
    assert (await db.execute(select(Employee))).scalars().all() == []

    anchor = await _employee(db, company, code="LEAVE-EMP")
    leave_rows = [{"employee_code": anchor.employee_id, "leave_type": "Earned Leave", "year": 2026, "balance_days": "10", "encashable": True, "basis": "GROSS", "divisor": 26}]
    first = await service.validate_payload(company_id=company.id, migration_type="OPENING_LEAVE_BALANCES", rows=leave_rows, actor_id=actor.id)
    await service.commit_batch(first.id, company_id=company.id)
    balance = (await db.execute(select(LeaveBalance))).scalar_one()
    assert balance.balance_days == Decimal("10") and balance.encashment_divisor == 26
    second = await service.validate_payload(company_id=company.id, migration_type="LEAVE_BALANCES", rows=[dict(leave_rows[0], balance_days="15")], actor_id=actor.id)
    await service.commit_batch(second.id, company_id=company.id)
    assert balance.balance_days == Decimal("15")
    await service.rollback_batch(second.id, company_id=company.id)
    await db.refresh(balance)
    assert balance.balance_days == Decimal("10")
    await service.rollback_batch(first.id, company_id=company.id)
    assert (await db.execute(select(LeaveBalance))).scalars().all() == []


@pytest.mark.asyncio
async def test_ytd_migration_commit_rollback_and_payslip_precedence(db):
    company = await _company(db)
    actor = await _user(db, company, "ytd")
    employee = await _employee(db, company, actor, code="YTD-EMP")
    service = DataMigrationService(db)
    rows = [{
        "employee_code": employee.employee_id, "period_month": 4, "period_year": 2025,
        "gross_earnings": "50000", "arrears": "1000", "tds": "2500",
        "total_deductions": "5000", "net_pay": "45000",
    }]
    batch = await service.validate_payload(company_id=company.id, migration_type="YTD_SALARY", rows=rows, actor_id=actor.id)
    assert batch.status == "VALIDATED"
    await service.commit_batch(batch.id, company_id=company.id)
    ledger = (await db.execute(select(EmployeeYTDSalary))).scalar_one()
    assert ledger.gross_earnings_paise == 5_000_000 and ledger.tds_paise == 250_000
    summary = await PayslipService.get_ytd_summary(db, employee.id, "2025-2026", company.id)
    april = next(row for row in summary["months"] if row["period_month"] == 4)
    assert april["source"] == "MIGRATION" and april["tds"] == 2500.0

    run = PayrollRun(id=uuid.uuid4(), company_id=company.id, period_month=4, period_year=2025, status="FINALIZED")
    db.add(run)
    await db.flush()
    payslip = Payslip(
        id=uuid.uuid4(), company_id=company.id, payroll_run_id=run.id, employee_id=employee.id,
        payslip_number=f"PAY-{uuid.uuid4().hex[:12]}", period_month=4, period_year=2025,
        total_days_in_month=30, paid_days=Decimal("30"), gross_earnings=Decimal("60000"),
        tds=Decimal("1000"), total_deductions=Decimal("4000"), net_pay=Decimal("56000"),
    )
    db.add(payslip)
    await db.flush()
    summary = await PayslipService.get_ytd_summary(db, employee.id, "2025-2026", company.id)
    april = next(row for row in summary["months"] if row["period_month"] == 4)
    assert april["source"] == "PAYSLIP"
    assert april["gross_earnings"] == 60000.0 and april["tds"] == 1000.0
    await service.rollback_batch(batch.id, company_id=company.id)
    assert (await db.execute(select(EmployeeYTDSalary))).scalars().all() == []


def test_gratuity_da_cap_leave_options_and_notice_waiver():
    assert FnfCalculationService.compute_gratuity(Decimal("50000"), date(2022, 1, 1), date(2024, 1, 1)) == Decimal("0.00")
    fixed = FnfCalculationService.compute_gratuity(
        Decimal("50000"), date(2025, 1, 1), date(2026, 1, 1), employment_type="FIXED_TERM", da_monthly=Decimal("10000"),
    )
    assert fixed > Decimal("0.00")
    capped = FnfCalculationService.compute_gratuity(
        Decimal("1000000"), date(2000, 1, 1), date(2026, 1, 1), da_monthly=Decimal("500000"),
    )
    assert capped == Decimal("2000000.00")
    assert FnfCalculationService.compute_leave_encashment(
        Decimal("12"), Decimal("60000"), basis="GROSS", gross_monthly=Decimal("90000"), divisor=26,
    ) == Decimal("41538.46")
    recovery, _ = FnfCalculationService.compute_notice_recovery(30, 10, Decimal("60000"), waived=True)
    assert recovery == Decimal("0.00")


def test_eight_canonical_letters_and_required_routes():
    assert len(CANONICAL_LETTER_NAMES) == 8
    assert set(CANONICAL_LETTER_NAMES) == {
        "Offer Letter", "Appointment Letter", "Confirmation Letter", "Increment Letter",
        "Transfer Letter", "Relieving Letter", "Experience Letter", "Warning Letter",
    }
    from app.api.v2.document_esign_api import router as document_router
    from app.api.v2.employee_bulk_api import router as employee_router
    from app.api.v2.data_migration_api import router as migration_router
    paths = {route.path for router in (document_router, employee_router, migration_router) for route in router.routes}
    assert "/documents/{doc_id}/request-esign" in paths
    assert "/documents/{doc_id}/sign" in paths
    assert "/documents/{doc_id}/audit-certificate" in paths
    assert "/employees/bulk-import" in paths and "/employees/bulk-export" in paths
    assert "/migrations/{batch_id}/commit" in paths and "/migrations/{batch_id}/rollback" in paths


@pytest.mark.asyncio
async def test_mock_seed_requires_explicit_environment(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    from scripts.seed import seed
    with pytest.raises(RuntimeError, match="APP_ENV=local_seed"):
        await seed()
