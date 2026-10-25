"""Tests for EPFO PF ECR & Challan Compliance Module.

Verifies:
1. UAN format (12-digit numeric) validation & KYC flags
2. Contribution breakdown (EE 12%, EPS 8.33% capped at ₹1,250, EPF diff 3.67%, EDLI 0.5% capped at ₹75, Admin 0.5% min ₹500)
3. International worker uncapped rules & age 58 EPS zero rule
4. EPFO ECR v2.0 exact 11-column format with #|~|# delimiter
5. Challan TRRN recording, payment tracking, and receipt upload
6. 12-Month Statutory Filing Calendar (15th due date, status badges, Sec 7Q interest, Sec 14B damages)
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole, UserAccountStatus
from app.models.payroll import Payslip, PayrollRun
from app.models.payroll_models import PayrollPeriod
from app.models.payroll_compliance import ComplianceChallan, ComplianceDueDate
from app.services.payroll.statutory_service import StatutoryService


def test_uan_format_validation():
    """Verify 12-digit numeric UAN validation on Employee model."""
    valid, err = Employee.validate_uan_format("101234567890")
    assert valid is True
    assert err == ""

    # Invalid lengths
    valid, err = Employee.validate_uan_format("12345")
    assert valid is False
    assert "12 numeric digits" in err

    valid, err = Employee.validate_uan_format("10123456789012")
    assert valid is False
    assert "12 numeric digits" in err

    # Non-numeric
    valid, err = Employee.validate_uan_format("1012345ABC90")
    assert valid is False
    assert "only numeric digits" in err

    # Empty / None
    valid, err = Employee.validate_uan_format(None)
    assert valid is False
    assert "missing" in err


def test_pf_contribution_breakdown_standard_ceiling():
    """Verify standard PF calculation with ₹15,000 statutory ceiling."""
    # Basic = ₹30,000 (3,000,000 paise). With ceiling, PF wage is ₹15,000 (1,500,000 paise).
    res = StatutoryService.calculate_pf(
        basic_paise=3000000,
        da_paise=0,
        pf_on_full_basic=False,
        is_pf_eligible=True,
        is_international_worker=False,
        pf_wage_ceiling_applicable=True,
    )
    assert res["pf_wage_paise"] == 1500000  # ₹15,000
    assert res["employee_pf_paise"] == 180000  # 12% of 15k = ₹1,800
    assert res["employer_eps_paise"] == 124950 or res["employer_eps_paise"] == 125000 or res["employer_eps_paise"] == min(125000, round(1500000 * 0.0833))
    # EPS is capped at ₹1,250 (125,000 paise)
    assert res["employer_eps_paise"] <= 125000
    # EPF difference + EPS = total employer 12% (₹1,800 = 180,000 paise)
    assert res["employer_epf_paise"] + res["employer_eps_paise"] == 180000
    # EDLI: 0.5% capped at ₹75 (7,500 paise)
    assert res["employer_edli_paise"] == 7500
    # Admin: 0.5% of 15k = ₹75 (7,500 paise)
    assert res["employer_admin_paise"] == 7500
    assert res["wage_ceiling_applied"] is True


def test_pf_contribution_international_worker():
    """Verify that international workers have NO statutory wage ceiling under EPFO rules."""
    # Basic = ₹40,000 (4,000,000 paise)
    res = StatutoryService.calculate_pf(
        basic_paise=4000000,
        da_paise=0,
        is_pf_eligible=True,
        is_international_worker=True,
        pf_wage_ceiling_applicable=True,
    )
    # Full basic is used
    assert res["pf_wage_paise"] == 4000000
    assert res["employee_pf_paise"] == 480000  # 12% of 40k = ₹4,800
    assert res["wage_ceiling_applied"] is False


def test_pf_contribution_age_58_no_eps():
    """Verify that employees aged 58 or older receive 0 EPS and full 12% in EPF."""
    res = StatutoryService.calculate_pf(
        basic_paise=1500000,
        da_paise=0,
        age=59,
    )
    assert res["employer_eps_paise"] == 0
    assert res["employer_epf_paise"] == 180000  # full 12% to EPF Account 1


def test_pf_contribution_opt_out():
    """Verify that opted-out employees have 0 PF contributions."""
    res = StatutoryService.calculate_pf(
        basic_paise=2500000,
        is_pf_eligible=False,
    )
    assert res["pf_wage_paise"] == 0
    assert res["employee_pf_paise"] == 0
    assert res["total_pf_liability_paise"] == 0


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _seed_compliance_test_env():
    """Seed test company, user, period, employee, and payslip."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    period_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(id=company_id, name="Compliance Test Corp")
        session.add(comp)

        from app.core.security import hash_password
        user = User(
            id=user_id,
            name="Compliance Admin",
            email=f"compliance_{user_id.hex[:6]}@example.com",
            phone=f"98{uuid.uuid4().int % 100000000:08d}",
            password_hash=hash_password("Password123!"),
            role=UserRole.HR_ADMIN,
            account_status=UserAccountStatus.ACTIVE.value,
            company_id=company_id,
        )
        session.add(user)

        period = PayrollPeriod(
            id=period_id,
            company_id=company_id,
            name="May 2026",
            period_month=5,
            period_year=2026,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            pay_date=date(2026, 6, 1),
            status="OPEN",
        )
        session.add(period)

        run = PayrollRun(
            id=run_id,
            company_id=company_id,
            period_id=period_id,
            period_month=5,
            period_year=2026,
            run_number=f"RUN-{user_id.hex[:6].upper()}",
            status="PROCESSED",
            total_employees=1,
            total_gross=Decimal("45000.00"),
            total_net=Decimal("38000.00"),
        )
        session.add(run)

        emp = Employee(
            id=emp_id,
            company_id=company_id,
            user_id=user_id,
            employee_id=f"EMP-{user_id.hex[:6].upper()}",
            first_name="VIKRAM",
            last_name="SINGH",
            personal_email=f"vikram_{user_id.hex[:6]}@example.com",
            phone=f"97{uuid.uuid4().int % 100000000:08d}",
            department="ENGINEERING",
            designation="Tech Lead",
            joining_date=date(2024, 1, 15),
            uan_number="101234567890",
            pan_number="ABCDE1234F",
            is_pf_eligible=True,
            is_international_worker=False,
            pf_wage_ceiling_applicable=True,
            basic_salary=Decimal("25000.00"),
            ctc=Decimal("600000.00"),
        )
        session.add(emp)

        ps = Payslip(
            id=uuid.uuid4(),
            company_id=company_id,
            payroll_run_id=run_id,
            employee_id=emp_id,
            payslip_number=f"PAY-{user_id.hex[:6].upper()}",
            period_month=5,
            period_year=2026,
            total_days_in_month=31,
            paid_days=Decimal("29.0"),
            lop_days=Decimal("2.0"),
            basic=Decimal("25000.00"),
            gross_earnings=Decimal("45000.00"),
            employee_pf=Decimal("1800.00"),
            employer_pf=Decimal("1800.00"),
            net_pay=Decimal("38000.00"),
        )
        session.add(ps)

        await session.commit()

    from app.utils.jwt import create_access_token
    token = create_access_token(user_id=str(user_id), role="hr_admin", company_id=str(company_id), email=f"compliance_{user_id.hex[:6]}@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    return {
        "company_id": company_id,
        "user_id": user_id,
        "emp_id": emp_id,
        "period_id": period_id,
        "headers": headers,
    }


@pytest.mark.asyncio
async def test_epfo_ecr_txt_generator_format(transport):
    """Verify endpoint GET /api/v2/payroll/statutory/pf-ecr generates exact 11 columns with #|~|# delimiter."""
    env = await _seed_compliance_test_env()
    period_id = env["period_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Download raw text file
        res = await ac.get(
            f"/api/v2/payroll/statutory/pf-ecr?period_id={period_id}&format=txt&download=true",
            headers=env["headers"],
        )
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        assert 'attachment; filename="EPFO_ECR_2026_05.txt"' in res.headers["content-disposition"]

        text_content = res.text
        assert "#|~|#" in text_content
        lines = [line for line in text_content.splitlines() if line.strip()]
        assert len(lines) == 1

        parts = lines[0].split("#|~|#")
        # Exact 11 columns
        assert len(parts) == 11
        assert parts[0] == "101234567890"  # UAN
        assert parts[1] == "VIKRAM SINGH"  # Clean uppercase Member Name
        assert parts[2] == "45000"  # Gross Wages
        assert parts[3] == "15000"  # EPF Wages (capped at ₹15,000)
        assert parts[4] == "15000"  # EPS Wages (capped at ₹15,000)
        assert parts[5] == "15000"  # EDLI Wages (capped at ₹15,000)
        assert parts[6] == "1800"  # EE Contribution (12% of 15k)
        assert parts[7] == "1250"  # EPS Contribution (8.33% capped at 1250)
        assert parts[8] == "550"  # EPF-EPS Diff (1800 - 1250 = 550)
        assert parts[9] == "2"  # NCP Days (2 LOP days)
        assert parts[10] == "0"  # Refund of Advances

        # 2. Get JSON response with metadata
        json_res = await ac.get(
            f"/api/v2/payroll/statutory/pf-ecr?period_id={period_id}&format=json",
            headers=env["headers"],
        )
        assert json_res.status_code == 200
        data = json_res.json()["data"]
        assert data["record_count"] == 1
        assert data["total_ee_share"] == 1800.0
        assert data["total_eps_share"] == 1250.0
        assert data["total_er_diff_share"] == 550.0
        assert data["admin_charges"] >= 500.0  # Minimum ₹500 statutory establishment rule
        assert data["has_missing_uan"] is False


@pytest.mark.asyncio
async def test_filing_calendar_and_overdue_interest(transport):
    """Verify 12-month Statutory Filing Calendar with 15th due date, badges, and Section 7Q/14B warnings."""
    env = await _seed_compliance_test_env()

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v2/payroll/statutory/filing-calendar?year=2026", headers=env["headers"])
        assert res.status_code == 200
        calendar = res.json()["data"]
        assert len(calendar) == 12

        # Verify May 2026 due date is June 15, 2026
        may_item = next(item for item in calendar if item["month"] == 5)
        assert may_item["due_date"] == "2026-06-15"
        assert may_item["wage_month_label"] == "May 2026"

        # Verify overdue items calculate Section 7Q (12% p.a.) interest
        for item in calendar:
            if item["is_overdue"]:
                assert item["status"] == "OVERDUE"
                assert item["overdue_days"] > 0
                assert item["interest_7q_amount"] > 0
                assert item["damages_14b_amount"] > 0
                assert item["damages_14b_rate_pct"] in (5.0, 10.0, 15.0, 25.0)


@pytest.mark.asyncio
async def test_challan_record_and_file_upload(transport):
    """Verify recording TRRN and uploading Challan PDF receipt."""
    env = await _seed_compliance_test_env()
    period_id = env["period_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Record TRRN
        record_payload = {
            "periodId": str(period_id),
            "trrnNumber": "TRRN101202605001",
            "challanGenerationDate": "2026-06-10",
            "paymentDate": "2026-06-12",
            "utrNumber": "UTIB00012345678",
            "totalAmount": 4175.0,
        }
        rec_res = await ac.post("/api/v2/payroll/statutory/challan/record", json=record_payload, headers=env["headers"])
        assert rec_res.status_code == 200
        assert rec_res.json()["data"]["trrn_number"] == "TRRN101202605001"
        assert rec_res.json()["data"]["status"] == "FILED_ON_TIME"

        # Upload Challan PDF (valid PDF magic bytes %PDF)
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n>>\n%%EOF"
        files = {
            "file": ("challan_receipt.pdf", io.BytesIO(pdf_content), "application/pdf")
        }
        data = {
            "period_id": str(period_id),
            "file_type": "CHALLAN",
        }
        up_res = await ac.post("/api/v2/payroll/statutory/challan/upload", data=data, files=files, headers=env["headers"])
        assert up_res.status_code == 200
        assert "file_url" in up_res.json()["data"]
        assert up_res.json()["data"]["file_type"] == "CHALLAN"


@pytest.mark.asyncio
async def test_uan_validation_audit_and_employee_update(transport):
    """Verify UAN validation report and updating employee PF parameters."""
    env = await _seed_compliance_test_env()
    emp_id = env["emp_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Audit
        audit_res = await ac.get("/api/v2/payroll/statutory/uan-validation", headers=env["headers"])
        assert audit_res.status_code == 200
        summary = audit_res.json()["data"]
        assert summary["total_active_employees"] >= 1
        assert summary["valid_uan_count"] >= 1

        # Update with valid UAN & flags
        update_payload = {
            "uanNumber": "109876543210",
            "isPfEligible": True,
            "isInternationalWorker": True,
            "pfWageCeilingApplicable": False,
        }
        up_res = await ac.patch(
            f"/api/v2/payroll/statutory/employee-pf/{emp_id}",
            json=update_payload,
            headers=env["headers"],
        )
        assert up_res.status_code == 200
        assert up_res.json()["data"]["uan_number"] == "109876543210"
        assert up_res.json()["data"]["is_international_worker"] is True
        assert up_res.json()["data"]["pf_wage_ceiling_applicable"] is False

        # Attempt invalid UAN length -> 422
        bad_payload = {"uanNumber": "123"}
        bad_res = await ac.patch(
            f"/api/v2/payroll/statutory/employee-pf/{emp_id}",
            json=bad_payload,
            headers=env["headers"],
        )
        assert bad_res.status_code == 422
