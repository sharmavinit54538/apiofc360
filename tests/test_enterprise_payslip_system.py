"""Comprehensive automated test suite for the OFC360 Enterprise Salary Slip PDF System.

Covers all 27 functional, financial, visual/layout, security, RBAC, isolation,
branding, versioning, verification, and non-blocking bulk generation requirements.
"""
from __future__ import annotations

import io
import os
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image as PILImage
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.database import get_db_session
from app.main import app
from app.models.company import Company
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.payroll import (
    OvertimeEntry,
    PayrollAuditLog,
    PayrollRun,
    Payslip,
    PayslipDocument,
    StatutoryComplianceConfig,
)
from app.models.payroll_models import PayrollPeriod, PayrollRunEmployee
from app.models.user import User
from app.models.user.role import RoleEnum
from app.services.payroll.payslip_formatter import (
    amount_in_words,
    build_payslip_filename,
    format_currency,
    format_indian_number,
    mask_account_number,
    mask_pan,
    mask_pf_number,
    mask_uan,
)
from app.services.payroll.payslip_pdf_renderer import (
    render_enterprise_payslip_pdf,
    validate_financial_reconciliation,
)
from app.services.payroll.payslip_service import PayslipService
from app.services.payroll.payslip_settings_service import (
    _UPLOAD_ROOT_ABS,
    resolve_safe_local_image_path,
)

TEST_TABLES = [
    "companies",
    "legal_entities",
    "branches",
    "departments",
    "shifts",
    "users",
    "employees",
    "employee_bank_accounts",
    "holiday_calendar",
    "payroll_periods",
    "pay_cycles",
    "payroll_runs",
    "payroll_run_employees",
    "salary_structures",
    "statutory_compliance_configs",
    "payslips",
    "payslip_documents",
    "payment_batches",
    "payment_batch_items",
    "overtime_entries",
    "employee_ytd_salaries",
    "payroll_audit_logs",
    "notifications",
]


def _extract_pdf_text(pdf_bytes: bytes, *, password: str | None = None) -> tuple[int, str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if reader.is_encrypted and password:
        reader.decrypt(password)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return len(reader.pages), "\n".join(pages_text)


@pytest_asyncio.fixture
async def db():
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _jsonb_sqlite(type_, compiler, **kwargs):  # noqa: ARG001
        return "JSON"

    tables = [Base.metadata.tables[name] for name in TEST_TABLES if name in Base.metadata.tables]
    default_restore, index_restore, seen_indexes = [], [], set()
    for table in tables:
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

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
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


def _make_auth_headers(
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    role: str = "hr_admin",
    permissions: list[str] | None = None,
) -> dict[str, str]:
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": role,
    }
    if permissions is not None:
        claims["permissions"] = permissions
    token = create_access_token(claims)
    return {"Authorization": f"Bearer {token}"}


async def _seed_payslip_scenario(
    db: AsyncSession,
    *,
    company_name: str = "Zenith Aerospace Systems Pvt Ltd",
    run_status: str = "PAID",
    with_branding: bool = True,
    with_logo_file: bool = False,
    with_signature_file: bool = False,
    with_bank: bool = True,
    with_statutory: bool = True,
    zero_deductions: bool = False,
    extra_earnings: dict[str, int] | None = None,
    extra_deductions: dict[str, int] | None = None,
    arrears: Decimal = Decimal("0.00"),
    bonus: Decimal = Decimal("0.00"),
    advance_recovery_paise: int = 0,
    overtime_paise: int = 0,
    employee_count: int = 1,
    emp_code_prefix: str = "EMP",
    emp_name_tuple: tuple[str, str] = ("Aarav", "Kulkarni"),
    payslip_settings_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    created_files: list[str] = []
    co_id = uuid.uuid4()

    ps_settings: dict[str, Any] = {}
    if with_branding:
        ps_settings = {
            "primary_color": "#182C43",
            "secondary_color": "#F5F7FA",
            "accent_color": "#0B665C",
            "company_legal_name": f"{company_name}",
            "registered_address": "Tower B, Outer Ring Road, Bellandur",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postal_code": "560103",
            "country": "India",
            "official_email": "payroll@zenithaero.example",
            "official_phone": "+91 80 4111 2200",
            "website": "https://zenithaero.example",
            "cin_number": "U72900KA2020PTC123456",
            "gstin": "29AAACZ1234F1Z5",
            "pf_establishment_code": "BG/BNG/0098765/000",
            "esic_registration_number": "53000987650000101",
            "hr_contact_name": "Nandini Deshmukh",
            "hr_designation": "Head of Payroll & Rewards",
            "hr_department": "People Operations & Payroll",
            "hr_email": "hr-helpdesk@zenithaero.example",
            "payroll_support_email": "payroll-support@zenithaero.example",
            "office_extension": "Extn 402",
            "signatory_name": "Rajeshwar Rao",
            "signatory_designation": "VP - Finance & Payroll",
            "signatory_department": "Finance & Compliance",
        }
    if with_logo_file:
        logos_dir = os.path.join(_UPLOAD_ROOT_ABS, "logos", str(co_id))
        os.makedirs(logos_dir, exist_ok=True)
        logo_path = os.path.join(logos_dir, "test_logo.png")
        img = PILImage.new("RGBA", (180, 64), (24, 44, 67, 255))
        img.save(logo_path, "PNG")
        created_files.append(logo_path)
        ps_settings["company_logo_url"] = f"/uploads/logos/{co_id}/test_logo.png"
    if with_signature_file:
        logos_dir = os.path.join(_UPLOAD_ROOT_ABS, "logos", str(co_id))
        os.makedirs(logos_dir, exist_ok=True)
        sig_path = os.path.join(logos_dir, "test_sig.png")
        img = PILImage.new("RGBA", (160, 48), (11, 102, 92, 255))
        img.save(sig_path, "PNG")
        created_files.append(sig_path)
        ps_settings["signature_image_url"] = f"/uploads/logos/{co_id}/test_sig.png"
    if payslip_settings_override:
        ps_settings.update(payslip_settings_override)

    company = Company(
        id=co_id,
        name=company_name,
        payslip_settings=ps_settings or None,
    )
    db.add(company)
    await db.flush()

    cfg = StatutoryComplianceConfig(
        id=uuid.uuid4(),
        company_id=co_id,
        is_active=True,
        state="Karnataka",
        country="India",
    )
    db.add(cfg)

    admin_user = User(
        id=uuid.uuid4(),
        company_id=co_id,
        name="HR Admin",
        email=f"hradmin_{uuid.uuid4().hex[:8]}@zenithaero.example",
        phone=f"99{uuid.uuid4().int % 100000000:08d}",
        password_hash="test-hash",
        role=RoleEnum.HR_ADMIN,
        is_verified=True,
    )
    db.add(admin_user)

    period = PayrollPeriod(
        id=uuid.uuid4(),
        company_id=co_id,
        name="November 2026",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 11, 30),
        period_month=11,
        period_year=2026,
        status="CLOSED" if run_status == "PAID" else "OPEN",
        is_locked=run_status in {"LOCKED", "PAID"},
    )
    db.add(period)

    run = PayrollRun(
        id=uuid.uuid4(),
        company_id=co_id,
        period_id=period.id,
        run_number=f"PR-2026-11-{uuid.uuid4().hex[:4].upper()}",
        period_month=11,
        period_year=2026,
        status=run_status,
        is_locked=run_status in {"LOCKED", "PAID"},
    )
    db.add(run)
    await db.flush()

    employees: list[Employee] = []
    users: list[User] = []
    payslips: list[Payslip] = []

    for idx in range(employee_count):
        uid = uuid.uuid4()
        u = User(
            id=uid,
            company_id=co_id,
            name=f"{emp_name_tuple[0]} {emp_name_tuple[1]} {idx}".strip(),
            email=f"emp{idx}_{uuid.uuid4().hex[:6]}@zenithaero.example",
            phone=f"98{uuid.uuid4().int % 100000000:08d}",
            password_hash="test-hash",
            role=RoleEnum.EMPLOYEE,
            is_verified=True,
        )
        db.add(u)
        users.append(u)

        emp = Employee(
            id=uuid.uuid4(),
            company_id=co_id,
            user_id=uid,
            employee_id=f"{emp_code_prefix}-{2001 + idx}",
            first_name=emp_name_tuple[0],
            last_name=emp_name_tuple[1] if employee_count == 1 else f"{emp_name_tuple[1]} {idx + 1}",
            personal_email=f"p_{idx}_{uuid.uuid4().hex[:6]}@example.org",
            company_email=f"emp{idx}_{uuid.uuid4().hex[:6]}@zenithaero.example",
            phone=f"97{uuid.uuid4().int % 100000000:08d}",
            date_of_birth=date(1993, 7, 14),
            department="Platform Engineering",
            designation="Staff Backend Engineer",
            work_location="Bengaluru HQ",
            employment_type="FULL_TIME",
            joining_date=date(2022, 4, 15),
            pan_number="ABCPK4321D" if with_statutory else None,
            uan_number="100987654321" if with_statutory else None,
            pf_number="BG/BNG/0098765/000/0012345" if with_statutory else None,
            esic_number="53000123450000101" if with_statutory else None,
            tax_regime="NEW" if with_statutory else None,
            role="employee",
            status="ACTIVE",
            is_deleted=False,
        )
        db.add(emp)
        await db.flush()
        employees.append(emp)

        if with_bank:
            db.add(
                EmployeeBankAccount(
                    id=uuid.uuid4(),
                    employee_id=emp.id,
                    bank_name="HDFC Bank Ltd",
                    account_holder_name=f"{emp.first_name} {emp.last_name}",
                    account_number="50100234567890",
                    ifsc_code="HDFC0000123",
                    account_type="SALARY",
                    is_primary=True,
                )
            )

        basic_p = 7_500_000  # Rs 75,000.00
        hra_p = 3_000_000    # Rs 30,000.00
        conv_p = 160_000     # Rs 1,600.00
        spec_p = 2_000_000   # Rs 20,000.00
        custom_earn = extra_earnings or {}
        bonus_p = int(bonus * 100)
        arrears_p = int(arrears * 100)
        var_map = {"OVERTIME": overtime_paise} if overtime_paise else {}
        variable_total_p = sum(var_map.values())
        custom_earn_sum = sum(custom_earn.values())
        gross_p = basic_p + hra_p + conv_p + spec_p + custom_earn_sum + variable_total_p + bonus_p + arrears_p

        if zero_deductions:
            pf_p = esi_p = pt_p = tds_p = 0
            ded_custom: dict[str, int] = {}
            total_ded_p = 0
        else:
            pf_p = 180_000
            esi_p = 0
            pt_p = 20_000
            tds_p = 850_000
            ded_custom = extra_deductions or {}
            total_ded_p = pf_p + esi_p + pt_p + tds_p + advance_recovery_paise + sum(ded_custom.values())

        net_p = gross_p - total_ded_p
        earnings_breakup: dict[str, Any] = {
            "basic_paise": basic_p,
            "hra_paise": hra_p,
            "conveyance_paise": conv_p,
            "special_paise": spec_p,
            "custom_paise": custom_earn,
            "variable_components_paise": var_map,
            "variable_paise": variable_total_p,
            "one_time_bonus_paise": bonus_p,
            "arrears_paise": arrears_p,
            "gross_paise": gross_p,
        }
        deductions_breakup: dict[str, Any] = {
            "pf_paise": pf_p,
            "esi_paise": esi_p,
            "pt_paise": pt_p,
            "tds_paise": tds_p,
            "advance_recovery_paise": advance_recovery_paise,
            "custom_paise": ded_custom,
            "total_deductions_paise": total_ded_p,
            "employer_pf": 1800.0 if not zero_deductions else 0.0,
            "employer_esi": 0.0,
            "tax_regime": "NEW",
        }
        db.add(
            PayrollRunEmployee(
                id=uuid.uuid4(),
                run_id=run.id,
                employee_id=emp.id,
                company_id=co_id,
                gross_earnings_paise=gross_p,
                total_deductions_paise=total_ded_p,
                net_pay_paise=net_p,
                paid_days=Decimal("30.0"),
                lop_days=Decimal("0.0"),
                status="PROCESSED",
                earnings_breakup=earnings_breakup,
                deductions_breakup=deductions_breakup,
            )
        )

        ps = Payslip(
            id=uuid.uuid4(),
            company_id=co_id,
            payroll_run_id=run.id,
            employee_id=emp.id,
            payslip_number=f"PAY-202611-{emp_code_prefix}{idx:03d}",
            period_month=11,
            period_year=2026,
            total_days_in_month=30,
            paid_days=Decimal("30.0"),
            lop_days=Decimal("0.0"),
            basic=Decimal(basic_p) / 100,
            hra=Decimal(hra_p) / 100,
            conveyance=Decimal(conv_p) / 100,
            special_allowance=Decimal(spec_p) / 100,
            other_allowances_total=Decimal(custom_earn_sum + variable_total_p) / 100,
            arrears=arrears,
            bonus=bonus,
            gross_earnings=Decimal(gross_p) / 100,
            employee_pf=Decimal(pf_p) / 100,
            employer_pf=Decimal("1800.00") if not zero_deductions else Decimal("0.00"),
            employee_esi=Decimal("0.00"),
            employer_esi=Decimal("0.00"),
            professional_tax=Decimal(pt_p) / 100,
            tds=Decimal(tds_p) / 100,
            other_deductions=Decimal(advance_recovery_paise + sum(ded_custom.values())) / 100,
            total_deductions=Decimal(total_ded_p) / 100,
            net_pay=Decimal(net_p) / 100,
            payment_status="PAID" if run_status == "PAID" else "PENDING",
            payment_date=date(2026, 11, 30) if run_status == "PAID" else None,
        )
        db.add(ps)
        payslips.append(ps)

    await db.commit()
    return {
        "company": company,
        "admin_user": admin_user,
        "run": run,
        "period": period,
        "employees": employees,
        "users": users,
        "payslips": payslips,
        "created_files": created_files,
    }


def _cleanup_files(paths: list[str]) -> None:
    for path in paths:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


# ── Pure Formatting, Masking & Words Unit Tests (Scenarios 15, 16, 27) ────────

def test_indian_formatting_words_and_pii_masking():
    assert format_indian_number("125000") == "1,25,000.00"
    assert format_indian_number("12345678.5") == "1,23,45,678.50"
    assert format_currency("267050.75", "INR") == "₹2,67,050.75"
    assert format_currency("1500", "USD") == "$1,500.00"

    assert amount_in_words("0.00") == "Indian Rupees Zero Only"
    assert amount_in_words("267050.00") == "Indian Rupees Two Lakh Sixty-Seven Thousand Fifty Only"
    assert amount_in_words("100000.50") == "Indian Rupees One Lakh and Fifty Paise Only"
    assert amount_in_words("12345678.05") == (
        "Indian Rupees One Crore Twenty-Three Lakh Forty-Five Thousand Six Hundred Seventy-Eight and Five Paise Only"
    )
    assert amount_in_words("900.25", "USD") == "US Dollars Nine Hundred and Twenty-Five Cents Only"

    assert mask_account_number("50100234567890") == "XXXXXXXXXX7890"
    assert mask_pan("ABCPK4321D") == "XXXXXX321D"
    assert mask_uan("100987654321") == "XXXXXXXX4321"
    assert mask_pf_number("BG/BNG/0098765/000/0012345", enabled=True).endswith("2345")
    assert mask_account_number(None) is None
    assert mask_pan("") is None

    fname = build_payslip_filename("EMP-2001", 11, 2026)
    assert fname == "Payslip_EMP-2001_November_2026.pdf"

    # SSRF / path traversal rejection
    assert resolve_safe_local_image_path("https://evil.example/logo.png") is None
    assert resolve_safe_local_image_path("http://127.0.0.1/logo.png") is None
    assert resolve_safe_local_image_path("../../etc/passwd") is None


# ── Scenarios 1, 2, 3, 4, 5, 6, 7, 13: PDF Rendering & Visual Completeness ──

@pytest.mark.asyncio
async def test_complete_corporate_payslip_with_logo_and_signature(db: AsyncSession):
    data = await _seed_payslip_scenario(
        db,
        with_branding=True,
        with_logo_file=True,
        with_signature_file=True,
    )
    try:
        ps = data["payslips"][0]
        pdf_bytes, filename, updated_ps, doc = await PayslipService.generate_and_store_payslip(
            db, payslip_id=ps.id, company_id=data["company"].id, release=True
        )
        assert pdf_bytes[:4] == b"%PDF"
        assert filename == "Payslip_EMP-2001_November_2026.pdf"
        assert updated_ps.document_id and updated_ps.sha256_hash
        assert doc and doc.is_draft is False and doc.status == "RELEASED"

        pages, txt = _extract_pdf_text(pdf_bytes)
        assert pages == 1
        assert "Zenith Aerospace Systems Pvt Ltd" in txt
        assert "Aarav Kulkarni" in txt
        assert "SALARY SLIP" in txt
        assert "November 2026" in txt
        assert "₹" in txt
        assert "Indian Rupees" in txt
        assert "XXXXXXXXXX7890" in txt
        assert "XXXXXX321D" in txt
        assert "Nandini Deshmukh" in txt
        assert "Rajeshwar Rao" in txt
        assert "DRAFT" not in txt
        assert "Powered by OFC360 Payroll Management System" in txt
        assert "Page 1 of 1" in txt
    finally:
        _cleanup_files(data["created_files"])


@pytest.mark.asyncio
async def test_missing_optional_fields_no_logo_no_signature_no_hr_contact(db: AsyncSession):
    data = await _seed_payslip_scenario(
        db,
        company_name="Minimalist Venture Works",
        with_branding=False,
        with_logo_file=False,
        with_signature_file=False,
        with_bank=False,
        with_statutory=False,
        zero_deductions=True,
    )
    ps = data["payslips"][0]
    pdf_bytes, _, _, _ = await PayslipService.generate_and_store_payslip(
        db, payslip_id=ps.id, company_id=data["company"].id
    )
    pages, txt = _extract_pdf_text(pdf_bytes)
    normalized = " ".join(txt.split())
    assert pages == 1
    assert "Minimalist Venture Works" in normalized
    assert "computer-generated salary slip and does not require a physical signature" in normalized
    # Ensure zero leaked literal "None" or "null"
    assert "None" not in txt
    assert "null" not in txt
    assert "₹0.00" in txt  # Total deductions 0.00 matches Gross == Net


@pytest.mark.asyncio
async def test_long_names_custom_components_ot_bonus_loan_arrears(db: AsyncSession):
    long_co = "International Advanced Computational Photonics and Clean Energy Manufacturing Corporation India Private Limited"
    data = await _seed_payslip_scenario(
        db,
        company_name=long_co,
        emp_name_tuple=("Venkatanarasimharajuvaripeta", "Subramanyam-Chakravarthy"),
        extra_earnings={"Mobile_&_Internet_Allowance": 250_000, "Shift_Night_Diff": 350_000},
        extra_deductions={"Canteen_Meal_Coupon": 150_000},
        arrears=Decimal("4500.00"),
        bonus=Decimal("10000.00"),
        advance_recovery_paise=500_000,
        overtime_paise=420_000,
    )
    ps = data["payslips"][0]
    pdf_bytes, _, _, _ = await PayslipService.generate_and_store_payslip(
        db, payslip_id=ps.id, company_id=data["company"].id
    )
    _, txt = _extract_pdf_text(pdf_bytes)
    assert "Venkatanarasimharajuvaripeta" in txt
    assert "Overtime Pay" in txt
    assert "One-Time Bonus" in txt
    assert "Arrears" in txt
    assert "Loan EMI / Salary Advance Recovery" in txt


# ── Scenario 14: Multi-page Ledger Auto Pagination & Repeated Headers ─────────

@pytest.mark.asyncio
async def test_multipage_ledger_pagination_and_repeated_headers():
    many_earnings = [{"label": f"Custom Allowance Component {i:02d}", "amount": "1000.00"} for i in range(1, 35)]
    many_deductions = [{"label": f"Custom Recovery Item {i:02d}", "amount": "200.00"} for i in range(1, 35)]
    snapshot = {
        "company": {"name": "Multipage Enterprise Ltd", "country": "India"},
        "employee": {
            "full_name": "Deepak Sharma",
            "employee_code": "EMP-MP01",
            "department": "Operations",
            "designation": "Lead Engineer",
            "employment_type": "Full Time",
            "joining_date_display": "01 Apr 2023",
            "work_location": "Mumbai",
            "period_label": "November 2026",
            "pay_period_range": "01 Nov 2026 - 30 Nov 2026",
            "payment_date_display": "30 Nov 2026",
            "payment_mode": "NEFT",
            "payment_status_display": "PAID",
            "payslip_number": "PAY-202611-MP01",
        },
        "bank_statutory": {"bank_name": "ICICI Bank", "masked_account_number": "XXXX9988"},
        "attendance": {"calendar_days": 30, "scheduled_working_days": 22, "present_days": "22.0", "paid_days": "30.0", "lop_days": "0.0"},
        "earnings": many_earnings,
        "deductions": many_deductions,
        "employer_contributions": [],
        "totals": {
            "currency": "INR",
            "gross_earnings": "34000.00",
            "total_deductions": "6800.00",
            "net_pay": "27200.00",
            "net_pay_words": amount_in_words("27200.00"),
        },
        "ytd_summary": {"has_data": False},
        "hr_support": {},
        "signatory": {"issue_date_display": "30 Nov 2026"},
        "verification": {
            "payslip_number": "PAY-202611-MP01",
            "document_id": "DOC-MP01-V1",
            "version_number": 1,
            "verification_token": "tok-mp-01",
            "verification_url": "https://verify.example/tok-mp-01",
            "is_draft": False,
        },
        "display_options": {"enable_qr_verification": True, "show_ofc360_footer": True},
    }
    pdf_bytes = render_enterprise_payslip_pdf(snapshot)
    pages, txt = _extract_pdf_text(pdf_bytes)
    assert pages >= 2
    assert "Page 1 of" in txt
    assert f"Page {pages} of {pages}" in txt
    assert "Custom Allowance Component 34" in txt
    assert "Custom Recovery Item 34" in txt


# ── Scenario 17: Financial Reconciliation Failure Must Reject Broken PDFs ───────

async def test_financial_reconciliation_mismatch_raises():
    bad_snapshot = {
        "earnings": [{"label": "Basic", "amount": "50000.00"}],
        "deductions": [{"label": "PF", "amount": "1800.00"}],
        "totals": {"gross_earnings": "50000.00", "total_deductions": "1800.00", "net_pay": "49000.00"},
    }
    with pytest.raises(ValueError, match="reconciliation mismatch"):
        validate_financial_reconciliation(bad_snapshot)

    with pytest.raises(ValueError, match="reconciliation mismatch"):
        render_enterprise_payslip_pdf(bad_snapshot)


# ── Scenarios 12 & 23: Versioning & Immutable Historical Snapshot Preservation ──

async def test_versioning_and_historical_snapshot_preservation(db: AsyncSession):
    data = await _seed_payslip_scenario(db, arrears=Decimal("0.00"))
    ps = data["payslips"][0]
    emp = data["employees"][0]
    co = data["company"]

    # Generate v1
    pdf_v1, _, ps_v1, doc_v1 = await PayslipService.generate_and_store_payslip(
        db, payslip_id=ps.id, company_id=co.id, release=True
    )
    assert doc_v1 and doc_v1.version_number == 1

    # Mutate live employee & company after issuance
    emp.designation = "Principal Architect"
    emp.department = "AI Research"
    co.name = "Renamed Corp After Merge"
    await db.commit()

    # Re-reading v1 returns preserved historical snapshot!
    pdf_cached, _, _, doc_cached = await PayslipService.generate_and_store_payslip(
        db, payslip_id=ps.id, company_id=co.id, force=False
    )
    assert pdf_cached == pdf_v1
    assert doc_cached.document_id == doc_v1.document_id
    _, txt_v1 = _extract_pdf_text(pdf_cached)
    assert "Staff Backend Engineer" in txt_v1
    assert "Zenith Aerospace Systems Pvt Ltd" in txt_v1
    assert "Principal Architect" not in txt_v1

    # Recalculation / correction -> emits v2 and marks v1 SUPERSEDED
    ps.arrears = Decimal("5000.00")
    ps.gross_earnings = ps.gross_earnings + Decimal("5000.00")
    ps.net_pay = ps.net_pay + Decimal("5000.00")
    await db.commit()

    pdf_v2, _, _, doc_v2 = await PayslipService.generate_and_store_payslip(
        db, payslip_id=ps.id, company_id=co.id, force=False
    )
    assert doc_v2.version_number == 2
    assert doc_v2.document_id != doc_v1.document_id
    await db.refresh(doc_v1)
    assert doc_v1.is_active is False
    assert doc_v1.status == "SUPERSEDED"
    _, txt_v2 = _extract_pdf_text(pdf_v2)
    assert "Principal Architect" in txt_v2


# ── Scenarios 18..26: End-to-End FastAPI RBAC, Isolation, Headers, Verify, Email ──

async def test_api_rbac_isolation_draft_watermark_verify_headers_and_email(db: AsyncSession):
    tenant_a = await _seed_payslip_scenario(db, company_name="Alpha Logistics Ltd", run_status="PAID", employee_count=2, emp_code_prefix="EMP")
    tenant_b = await _seed_payslip_scenario(db, company_name="Beta Retail Ltd", run_status="PAID", employee_count=1, emp_code_prefix="BET")
    draft_run_data = await _seed_payslip_scenario(db, company_name="Draft Preview Corp", run_status="PROCESSED", employee_count=1, emp_code_prefix="DRF")

    co_a = tenant_a["company"]
    admin_a = tenant_a["admin_user"]
    emp_a1, emp_a2 = tenant_a["employees"]
    ps_a1, ps_a2 = tenant_a["payslips"]
    admin_b = tenant_b["admin_user"]

    # Create a direct Manager user & a Super Admin user
    mgr_user = User(
        id=uuid.uuid4(),
        company_id=co_a.id,
        name="Manager User",
        email=f"mgr_{uuid.uuid4().hex[:6]}@alpha.example",
        phone="9111222333",
        password_hash="hash",
        role=RoleEnum.MANAGER,
        is_verified=True,
    )
    db.add(mgr_user)
    mgr_emp = Employee(
        id=uuid.uuid4(),
        company_id=co_a.id,
        user_id=mgr_user.id,
        employee_id="MGR-01",
        first_name="Vikram",
        last_name="Sen",
        personal_email="mgr.p@alpha.example",
        phone="9111222334",
        department="Platform Engineering",
        designation="Engineering Manager",
        joining_date=date(2021, 5, 1),
        role="manager",
        status="ACTIVE",
        is_deleted=False,
    )
    db.add(mgr_emp)
    await db.flush()
    emp_a1.reporting_manager_id = mgr_emp.id
    await db.commit()

    sa_id = uuid.uuid4()
    sa_user = User(
        id=sa_id,
        company_id=None,
        name="Super Admin",
        email=f"sa_{uuid.uuid4().hex[:6]}@ofc360.example",
        phone=f"97{uuid.uuid4().int % 100000000:08d}",
        password_hash="hash",
        role=RoleEnum.SUPER_ADMIN,
        is_active=True,
        is_verified=True,
    )
    db.add(sa_user)
    await db.commit()
    headers_admin_a = _make_auth_headers(user_id=admin_a.id, company_id=co_a.id, role="hr_admin")
    headers_admin_b = _make_auth_headers(user_id=admin_b.id, company_id=tenant_b["company"].id, role="hr_admin")
    headers_emp_a1 = _make_auth_headers(user_id=emp_a1.user_id, company_id=co_a.id, role="employee")
    headers_emp_a2 = _make_auth_headers(user_id=emp_a2.user_id, company_id=co_a.id, role="employee")
    headers_mgr_no_perm = _make_auth_headers(user_id=mgr_user.id, company_id=co_a.id, role="manager")
    headers_mgr_with_perm = _make_auth_headers(
        user_id=mgr_user.id,
        company_id=co_a.id,
        role="manager",
        permissions=["payroll:view_payslips"],
    )
    headers_super_admin = _make_auth_headers(user_id=sa_id, company_id=co_a.id, role="super_admin")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db_session] = _override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Super Admin denied across all payslip endpoints (Scenario 21)
            assert (await client.get("/api/v2/payroll/payslips", headers=headers_super_admin)).status_code == 403
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf", headers=headers_super_admin)).status_code == 403
            assert (await client.get("/api/v2/payroll/my-payslips", headers=headers_super_admin)).status_code == 403
            assert (await client.get("/api/v2/payroll/payslips/settings", headers=headers_super_admin)).status_code == 403
            assert (await client.get("/api/v2/pwa/payslips", headers=headers_super_admin)).status_code == 403

            # 2. Reporting hierarchy alone does NOT allow manager to access reportee payslip (Scenario 22)
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf", headers=headers_mgr_no_perm)).status_code == 403
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf", headers=headers_mgr_with_perm)).status_code == 403

            # Grant explicit company policy flag -> now manager WITH permission succeeds
            r_policy = await client.patch(
                "/api/v2/payroll/payslips/settings",
                json={"hr_department": "Payroll Helpdesk", "primary_color": "#1E3A5F"},
                headers=headers_admin_a,
            )
            assert r_policy.status_code == 200
            co_a.hr_settings = {"allow_manager_payslip_access": True}
            await db.commit()
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf", headers=headers_mgr_with_perm)).status_code == 200
            # Still reject SSRF remote image URLs in settings
            r_ssrf = await client.patch(
                "/api/v2/payroll/payslips/settings",
                json={"company_logo_url": "https://attacker.invalid/logo.png"},
                headers=headers_admin_a,
            )
            assert r_ssrf.status_code == 422

            # 3. Cross-employee forbidden (Scenario 19)
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf", headers=headers_emp_a2)).status_code == 403
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}", headers=headers_emp_a2)).status_code == 403

            # 4. Cross-tenant isolation (Scenario 20)
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}", headers=headers_admin_b)).status_code == 404
            assert (await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf", headers=headers_admin_b)).status_code == 404
            assert (await client.get(f"/api/payroll/payslips/{ps_a1.id}/preview", headers=headers_admin_b)).status_code == 404

            # 5. Official bulk generate & download security headers (Scenario 18 & 24)
            r_bulk = await client.post(
                "/api/v2/payroll/payslips/bulk-generate",
                json={"run_id": str(tenant_a["run"].id)},
                headers=headers_admin_a,
            )
            assert r_bulk.status_code == 200
            assert r_bulk.json()["data"]["generated_count"] == 2

            r_dl = await client.get(
                f"/api/v2/payroll/my-payslips/{tenant_a['run'].id}/download",
                headers=headers_emp_a1,
            )
            assert r_dl.status_code == 200
            assert r_dl.headers["content-type"] == "application/pdf"
            assert "private, no-store" in r_dl.headers.get("cache-control", "")
            assert r_dl.headers.get("x-content-type-options") == "nosniff"
            assert r_dl.content[:4] == b"%PDF"

            # Signed short-lived URL works & rejected on invalid token
            r_signed = await client.post(
                f"/api/v2/payroll/payslips/{ps_a1.id}/signed-url",
                headers=headers_emp_a1,
            )
            assert r_signed.status_code == 200
            signed_tok = r_signed.json()["data"]["token"]
            assert (
                await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf?token={signed_tok}", headers=headers_emp_a1)
            ).status_code == 200
            assert (
                await client.get(f"/api/v2/payroll/payslips/{ps_a1.id}/pdf?token=bad.sig", headers=headers_emp_a1)
            ).status_code == 403

            # 6. Public QR Verification endpoint leaks ZERO PII or salary amounts (Scenario 26)
            await db.refresh(ps_a1)
            r_verify = await client.get(f"/api/v2/payroll/payslips/verify/{ps_a1.verification_token}")
            assert r_verify.status_code == 200
            v_data = r_verify.json()["data"]
            assert v_data["valid"] is True
            assert v_data["is_draft"] is False
            assert v_data["integrity_verified"] is True
            assert v_data["payslip_number"] == ps_a1.payslip_number
            assert "company_name" in v_data
            raw_verify_text = str(v_data)
            for forbidden in ("Aarav", "Kulkarni", "ABCPK", "7890", "75000", "net_pay", "gross"):
                assert forbidden not in raw_verify_text

            # 7. Draft / non-finalized run cannot produce official bulk generation (409), only draft watermark
            draft_headers = _make_auth_headers(
                user_id=draft_run_data["admin_user"].id,
                company_id=draft_run_data["company"].id,
                role="hr_admin",
            )
            assert (
                await client.post(
                    "/api/v2/payroll/payslips/bulk-generate",
                    json={"run_id": str(draft_run_data["run"].id), "allow_draft": False},
                    headers=draft_headers,
                )
            ).status_code == 409

            draft_ps = draft_run_data["payslips"][0]
            draft_pdf_resp = await client.get(
                f"/api/v2/payroll/payslips/{draft_ps.id}/pdf?allow_draft=true",
                headers=draft_headers,
            )
            assert draft_pdf_resp.status_code == 200
            _, draft_txt = _extract_pdf_text(draft_pdf_resp.content)
            assert "DRAFT" in draft_txt
            await db.refresh(draft_ps)
            r_draft_verify = await client.get(f"/api/v2/payroll/payslips/verify/{draft_ps.verification_token}")
            assert r_draft_verify.json()["data"]["valid"] is False
            assert r_draft_verify.json()["data"]["is_draft"] is True

            # 8. Email delivery flow with password protection option (Scenario 25)
            with patch("app.services.payroll.payslip_service.send_email", new=AsyncMock(return_value=True)) as mock_send:
                r_email = await client.post(
                    f"/api/v2/payroll/payslips/{ps_a1.id}/email?is_password_protected=true",
                    headers=headers_admin_a,
                )
                assert r_email.status_code == 200
                mock_send.assert_awaited_once()
                att_name, att_bytes, att_mime = mock_send.call_args.kwargs["attachments"][0]
                assert att_name == "Payslip_EMP-2001_November_2026.pdf"
                assert att_mime == "application/pdf"
                reader = PdfReader(io.BytesIO(att_bytes))
                assert reader.is_encrypted is True
                pw = PayslipService.derive_payslip_password(emp_a1, ps_a1)
                assert reader.decrypt(pw)
    finally:
        app.dependency_overrides.clear()


# ── Scenario 18 (scale): Concurrent Batch Rendering Across 12 Employees ────────

async def test_concurrent_bulk_batch_payslip_generation(db: AsyncSession):
    data = await _seed_payslip_scenario(db, employee_count=12, emp_code_prefix="BLK")
    count = await PayslipService.generate_batch_payslips(
        db,
        data["run"].id,
        company_id=data["company"].id,
        require_finalized=True,
        release=True,
    )
    assert count == 12
    docs = (
        await db.execute(
            select(PayslipDocument).where(PayslipDocument.payroll_run_id == data["run"].id)
        )
    ).scalars().all()
    assert len(docs) == 12
    assert len({d.document_id for d in docs}) == 12
    assert len({d.sha256_hash for d in docs}) == 12
    audit_count = (
        await db.execute(
            select(PayrollAuditLog).where(
                PayrollAuditLog.entity_id == data["run"].id,
                PayrollAuditLog.action == "BULK_PAYSLIP_GENERATE",
            )
        )
    ).scalar_one_or_none()
    assert audit_count is not None
