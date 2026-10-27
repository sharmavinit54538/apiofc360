"""Step 4 Batch 2 statutory compliance golden and integration tests.

The suite deliberately uses integer paise and a real SQLite metadata harness.
PostgreSQL-only JSONB defaults are shimmed in the same way as the Step 3 tests;
no external payroll or filing service is required.
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.db.base import Base
from app.db.database import get_db_session
from app.main import create_app
from app.middleware.auth import get_current_user_claims
import app.models  # noqa: F401
from app.models.company import Company
from app.models.employee import Employee
from app.models.payroll import EmployeeInvestmentDeclaration, PayrollRun, Payslip
from app.models.payroll_compliance import ComplianceChallan, StateStatutoryRule
from app.models.payroll_models import PayrollPeriod
from app.services.payroll.statutory_service import StatutoryService


TEST_TABLES = (
    "companies", "users", "employees", "payroll_periods", "payroll_runs", "payslips",
    "statutory_compliance_configs", "payroll_compliance", "payroll_compliance_challans",
    "payroll_compliance_due_dates", "state_statutory_rules", "financial_year_tax_rules",
    "statutory_forms", "employee_investment_declarations", "tax_declaration_proofs",
    "employee_tax_info",
)


@pytest.fixture
async def db_session():
    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = lambda self, type_, **kw: "JSON"
    tables = [Base.metadata.tables[name] for name in TEST_TABLES]
    defaults = []
    for table in tables:
        for column in table.columns:
            if column.server_default and "jsonb" in str(column.server_default.arg).lower():
                defaults.append((column, column.server_default))
                column.server_default = None
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    finally:
        for column, default in defaults:
            column.server_default = default
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_payroll(db_session):
    company = Company(id=uuid.uuid4(), name="Statutory Test Co")
    employee = Employee(
        id=uuid.uuid4(), company_id=company.id, employee_id="EMP-STAT-001",
        first_name="Vikram", last_name="Singh", personal_email=f"vikram-{uuid.uuid4().hex[:6]}@example.com",
        phone="9876543210", department="Engineering", designation="Engineer",
        joining_date=date(2024, 1, 10), pan_number="ABCDE1234F", uan_number="101234567890",
        gender="MALE", state_code="MH", is_pf_eligible=True, pf_membership_active=True,
        basic_salary=Decimal("25000"), ctc=Decimal("600000"),
    )
    period = PayrollPeriod(
        id=uuid.uuid4(), company_id=company.id, name="May 2026", period_month=5, period_year=2026,
        start_date=date(2026, 5, 1), end_date=date(2026, 5, 31), pay_date=date(2026, 6, 1), status="OPEN",
    )
    run = PayrollRun(
        id=uuid.uuid4(), company_id=company.id, period_id=period.id, period_month=5, period_year=2026,
        run_number=f"RUN-{uuid.uuid4().hex[:8]}", status="PROCESSED", total_employees=1,
        total_gross=Decimal("45000"), total_net=Decimal("38000"),
    )
    payslip = Payslip(
        id=uuid.uuid4(), company_id=company.id, payroll_run_id=run.id, employee_id=employee.id,
        payslip_number=f"PAY-{uuid.uuid4().hex[:8]}", period_month=5, period_year=2026,
        total_days_in_month=31, paid_days=Decimal("31"), lop_days=Decimal("0"),
        basic=Decimal("25000"), hra=Decimal("10000"), gross_earnings=Decimal("45000"),
        employee_pf=Decimal("1800"), employer_pf=Decimal("1800"), employee_esi=Decimal("0"),
        employer_esi=Decimal("0"), professional_tax=Decimal("200"), tds=Decimal("1000"),
        total_deductions=Decimal("3000"), net_pay=Decimal("42000"),
    )
    db_session.add_all([company, employee, period, run, payslip])
    await db_session.commit()
    return company, employee, period, run, payslip


def test_pf_vpf_higher_wage_and_uan_membership():
    result = StatutoryService.calculate_pf(
        basic_paise=3_000_000, vpf_rate=Decimal("0.05"), uan_number="101234567890", require_uan=True,
    )
    assert result["employee_epf_paise"] == 180_000
    assert result["employee_vpf_paise"] == 75_000
    assert result["employee_pf_paise"] == 255_000
    assert result["employer_eps_paise"] == 125_000
    higher = StatutoryService.calculate_pf(basic_paise=3_000_000, pf_higher_wage_opted=True)
    assert higher["eps_wage_paise"] == 3_000_000
    inactive = StatutoryService.calculate_pf(basic_paise=3_000_000, pf_membership_active=False)
    assert inactive["total_pf_liability_paise"] == 0
    with pytest.raises(ValueError):
        StatutoryService.calculate_pf(basic_paise=1_000_000, uan_number="123", require_uan=True)


@pytest.mark.asyncio
async def test_pf_ecr_v2_download_has_eleven_hash_tilde_columns(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    result = await StatutoryService.generate_pf_ecr(db_session, period.id, company.id)
    lines = [line for line in result["ecr_text"].splitlines() if line]
    assert len(lines) == 1
    parts = lines[0].split("#~#")
    assert len(parts) == 11
    assert parts[:6] == ["101234567890", "VIKRAM SINGH", "45000", "15000", "15000", "15000"]
    assert parts[6:9] == ["1800", "1250", "550"]
    assert "#|~|#" not in result["ecr_text"]

    app = create_app()
    async def override_db():
        yield db_session
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(uuid.uuid4()), "role": "hr_admin", "company_id": str(company.id)}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v2/payroll/statutory/pf-ecr/download?period_id={period.id}")
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith("text/plain")
            assert len(response.text.strip().split("#~#")) == 11
    finally:
        app.dependency_overrides.clear()


def test_esi_pwd_ceiling_and_six_month_contribution_lock():
    assert not StatutoryService.calculate_esi(2_200_000)["is_applicable"]
    pwd = StatutoryService.calculate_esi(2_200_000, is_pwd=True)
    assert pwd["is_applicable"] and pwd["ceiling_paise"] == 2_500_000
    locked = StatutoryService.calculate_esi(
        2_200_000, covered_at_period_start=True, as_of_date=date(2026, 8, 15),
        contribution_period_start=date(2026, 4, 1),
    )
    assert locked["is_applicable"] and locked["contribution_period_lock"]
    assert locked["employee_esi_paise"] == 16_500
    next_period = StatutoryService.calculate_esi(
        2_200_000, covered_at_period_start=True, as_of_date=date(2026, 10, 15),
        contribution_period_start=date(2026, 4, 1),
    )
    assert not next_period["is_applicable"]


@pytest.mark.asyncio
async def test_esi_challan_is_persisted_and_downloadable(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    payslip.gross_earnings = Decimal("18000")
    await db_session.commit()
    result = await StatutoryService.generate_esi_challan(db_session, period.id, company.id)
    assert result["challan_type"] == "ESIC_CHALLAN"
    assert result["total_esi_paise"] == 72000
    stored = (await db_session.execute(select(ComplianceChallan).where(ComplianceChallan.id == uuid.UUID(result["challan_id"])))).scalar_one()
    assert stored.total_amount == Decimal("720.00")
    assert stored.file_payload and "IP Number" in stored.file_payload


def test_dynamic_pt_lwf_and_maharashtra_february():
    assert StatutoryService.calculate_pt(2_000_000, "MH", 2, "MALE")["pt_paise"] == 30_000
    assert StatutoryService.calculate_pt(2_000_000, "MH", 3, "MALE")["pt_paise"] == 20_000
    custom = StateStatutoryRule(
        state_code="RJ", state_name="Rajasthan", effective_from=date(2020, 1, 1),
        pt_slabs_json=[{"min_gross_paise": 0, "max_gross_paise": None, "amount_paise": 12_345}],
        lwf_employee_paise=500, lwf_employer_paise=1_000, lwf_frequency="MONTHLY", lwf_applicable_months=[5],
    )
    assert StatutoryService.calculate_pt(2_000_000, "RJ", 5, rule=custom)["pt_paise"] == 12_345
    assert StatutoryService.calculate_lwf(2_000_000, "RJ", 5, rule=custom)["employer_lwf_paise"] == 1_000
    assert StatutoryService.calculate_lwf(2_000_000, "RJ", 6, rule=custom)["employee_lwf_paise"] == 0
    assert StatutoryService.calculate_lwf(2_000_000, "MH", 6)["employee_lwf_paise"] == 1_200
    assert StatutoryService.calculate_lwf(2_000_000, "MH", 7)["employee_lwf_paise"] == 0


def test_old_new_tds_math_proration_bonus_and_verified_declarations():
    old = StatutoryService.calculate_tds(80_000_000, "OLD", financial_year="2024-2025")
    assert old["taxable_income_paise"] == 75_000_000
    assert old["annual_tax_paise"] == 6_500_000  # ₹62,500 tax + ₹2,500 cess
    new = StatutoryService.calculate_tds(77_500_000, "NEW", financial_year="2024-2025")
    assert new["taxable_income_paise"] == 70_000_000
    assert new["annual_tax_paise"] == 0  # 87A rebate
    prorated = StatutoryService.calculate_tds(
        80_000_000, "OLD", financial_year="2024-2025", remaining_months=5, ytd_tds_paise=1_500_000,
    )
    assert prorated["monthly_tds_paise"] == 1_000_000
    verified = StatutoryService.calculate_tds(
        80_000_000, "OLD", declarations={"section_80c": 0},
        verified_declarations={"section_80c": 150_000}, proof_cutoff_passed=True,
    )
    assert verified["declaration_source"] == "VERIFIED"
    assert verified["chapter_via_deduction_paise"] == 15_000_000
    bonus = StatutoryService.calculate_tds(80_000_000, "OLD", one_time_bonus_paise=10_000_000)
    assert bonus["one_time_bonus_tax_paise"] > 0


@pytest.mark.asyncio
async def test_esi_and_lwf_summary_routes(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    app = create_app()
    async def override_db():
        yield db_session
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(uuid.uuid4()), "role": "hr_admin", "company_id": str(company.id)}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            esi = await client.get(f"/api/v2/payroll/statutory/esi-return?period_id={period.id}&format=json")
            assert esi.status_code == 200, esi.text
            assert esi.json()["data"]["record_count"] == 1
            lwf = await client.get(f"/api/v2/payroll/statutory/lwf-summary?period_id={period.id}")
            assert lwf.status_code == 200, lwf.text
            assert lwf.json()["data"]["states"][0]["state_code"] == "MH"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_form138_draft_and_form130_pdf_download(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    db_session.add(ComplianceChallan(
        id=uuid.uuid4(), company_id=company.id, period_id=period.id, challan_type="TDS_CHALLAN",
        period_month=5, period_year=2026, bsr_code="0123456", challan_serial_number="000123",
        payment_date=date(2026, 6, 7), total_amount=Decimal("1000"),
    ))
    await db_session.commit()
    draft = await StatutoryService.generate_form138_draft(db_session, period.id, company.id)
    assert draft["is_valid"], draft["validation_errors"]
    assert draft["challan"]["bsr_code"] == "0123456"
    assert draft["rows"][0]["pan"] == "ABCDE1234F"

    app = create_app()
    async def override_db():
        yield db_session
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(uuid.uuid4()), "role": "hr_admin", "company_id": str(company.id)}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v2/payroll/statutory/form-130/download?employee_id={employee.id}&financial_year=2026-2027")
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith("application/pdf")
            assert response.content.startswith(b"%PDF")
            assert len(response.content) > 500
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_challan_crn_bank_reference_and_form138_validation(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    result = await StatutoryService.record_challan(db_session, company.id, {
        "period_id": str(period.id), "trrn_number": "TRRN-1", "crn_number": "CRN-1",
        "bank_reference": "BANK-UTR-1", "payment_date": "2026-06-12", "total_amount": "4175.00",
    })
    assert result["crn_number"] == "CRN-1"
    assert result["bank_reference"] == "BANK-UTR-1"
    invalid = await StatutoryService.generate_form138_draft(db_session, period.id, company.id)
    assert not invalid["is_valid"]
    assert any(error["field"] == "bsr_code" for error in invalid["validation_errors"])


@pytest.mark.asyncio
async def test_esi_return_infers_lock_from_first_contribution_period_payslip(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    april_run = PayrollRun(
        id=uuid.uuid4(), company_id=company.id, period_id=None, period_month=4, period_year=2026,
        run_number=f"RUN-{uuid.uuid4().hex[:8]}", status="PROCESSED", total_employees=1,
        total_gross=Decimal("20000"), total_net=Decimal("19000"),
    )
    db_session.add(april_run)
    await db_session.flush()
    db_session.add(Payslip(
        id=uuid.uuid4(), company_id=company.id, payroll_run_id=april_run.id, employee_id=employee.id,
        payslip_number=f"PAY-{uuid.uuid4().hex[:8]}", period_month=4, period_year=2026,
        total_days_in_month=30, paid_days=Decimal("30"), lop_days=Decimal("0"),
        basic=Decimal("12000"), gross_earnings=Decimal("20000"), net_pay=Decimal("19000"),
    ))
    await db_session.commit()
    result = await StatutoryService.generate_esi_return(db_session, period.id, company.id)
    assert result["items"][0]["is_applicable"]
    assert result["items"][0]["contribution_period_lock"]
    assert result["items"][0]["employee_esi_paise"] == 33_800


@pytest.mark.asyncio
async def test_declaration_proof_upload_and_verification_workflow(db_session):
    company, employee, period, run, payslip = await _seed_payroll(db_session)
    app = create_app()
    async def override_db():
        yield db_session
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user_claims] = lambda: {"sub": str(uuid.uuid4()), "role": "hr_admin", "company_id": str(company.id)}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(f"/api/v2/tax/declarations/{employee.id}", json={"financial_year": "2026-2027", "tax_regime": "OLD", "section_80c": "150000"})
            assert created.status_code == 200, created.text
            declaration_id = created.json()["data"]["id"]
            pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
            uploaded = await client.post(
                f"/api/v2/tax/declarations/{declaration_id}/proofs?section=80C&amount_claimed=150000",
                files={"file": ("80c-proof.pdf", io.BytesIO(pdf), "application/pdf")},
            )
            assert uploaded.status_code == 200, uploaded.text
            proof_id = uploaded.json()["data"]["id"]
            verified = await client.post(f"/api/v2/tax/proofs/{proof_id}/verify", json={"approved_amount": 150000})
            assert verified.status_code == 200, verified.text
            assert verified.json()["data"]["status"] == "VERIFIED"
            declaration = (await db_session.execute(select(EmployeeInvestmentDeclaration).where(EmployeeInvestmentDeclaration.id == uuid.UUID(declaration_id)))).scalar_one()
            assert declaration.use_verified_amounts
            assert declaration.proof_status == "VERIFIED"
    finally:
        app.dependency_overrides.clear()
