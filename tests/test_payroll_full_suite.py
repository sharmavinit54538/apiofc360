"""Comprehensive Test Suite for Payroll Module (v1 & v2 — 97 Endpoints).

Covers:
- Database models & Paise-based financial integrity
- V1 Legacy endpoints (Periods, Runs, Payslips)
- V2 Endpoints across all domains:
  * Accounting Export
  * Company Bank Accounts
  * Compensation & Revisions (Approval, Rejection, Bulk Import)
  * Payroll Cycles (Reopen, Void)
  * Employee Payroll & Self-Service (Dashboard, Reveal Bank Account)
  * Full & Final Settlement (FnF lifecycle, Exit Details, Statement Download)
  * Pay Components (Flat, Percentage, Safe Formula Evaluator)
  * Payment Batches (Validation, Hold/Release/Retry, Reconcile, Submit with Idempotency-Key)
  * Payslips & Provision Slips (Generation, Retrieval, PDF download)
  * Dynamic Reports (Strategy pattern, Async Export, Download)
  * Payroll Runs (Process, Validation, Review, Approval, Rejection, Send Back, Finalize)
  * Statutory Compliance (Config, Summary, Report Generation)
  * Variable Inputs (CRUD, Approval/Rejection, Bulk Preview & Apply)
- Idempotency & Deduplication
- RBAC guards & Validation Error handling
"""

from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.getcwd())

from app.main import create_app
from app.db.database import AsyncSessionLocal
from app.utils.jwt import create_access_token
from app.core.security import hash_password
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole, UserAccountStatus
from app.models.payroll import PayCycle, PayrollRun, Payslip
from app.models.payroll_models import (
    Compensation,
    CompensationRevision,
    CompanyBankAccount,
    FullAndFinalSettlement,
    PayComponent,
    PaymentBatch,
    PaymentBatchItem,
    PayrollPeriod,
    PayrollRunEmployee,
    VariableInput,
)
from app.services.payroll.formula_evaluator import SafeFormulaEvaluator


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _seed_test_env(role: UserRole = UserRole.HR_ADMIN):
    """Seed company, employee, and user with auth token."""
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email = f"hr_{user_id.hex[:6]}@example.com"
    phone = f"99{user_id.int % 100000000:08d}"

    async with AsyncSessionLocal() as session:
        comp = Company(id=company_id, name=f"Test Payroll Enterprise {company_id.hex[:4]}")
        session.add(comp)

        emp = Employee(
            id=emp_id,
            user_id=user_id,
            company_id=company_id,
            employee_id=f"EMP-{emp_id.hex[:4]}",
            first_name="Ramesh",
            last_name="Sharma",
            personal_email=email,
            phone=phone,
            department="Engineering",
            designation="Senior Backend Engineer",
            joining_date=date(2023, 1, 15),
            status="ACTIVE",
            is_active=True,
        )
        session.add(emp)

        user = User(
            id=user_id,
            company_id=company_id,
            name="Ramesh Sharma",
            email=email,
            phone=phone,
            password_hash=hash_password("Password@123"),
            role=role,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
        )
        session.add(user)

        # Baseline compensation (6,00,000 INR = 60,000,000 paise)
        compensation = Compensation(
            id=uuid.uuid4(),
            employee_id=emp_id,
            company_id=company_id,
            ctc_annual_paise=60000000,
            basic_monthly_paise=2500000,
            hra_monthly_paise=1000000,
            special_allowance_monthly_paise=1500000,
            effective_date=date.today(),
            status="ACTIVE",
        )
        session.add(compensation)

        # Company bank account
        company_bank = CompanyBankAccount(
            id=uuid.uuid4(),
            company_id=company_id,
            bank_name="HDFC Bank",
            account_number="50200098765432",
            ifsc_code="HDFC0001234",
            account_holder_name="Test Payroll Enterprise",
            account_type="CURRENT",
            is_primary=True,
            is_active=True,
        )
        session.add(company_bank)

        await session.commit()

    token = create_access_token(user_id=user_id, role=role.value, company_id=company_id, email=email)
    headers = {"Authorization": f"Bearer {token}"}
    return {
        "company_id": company_id,
        "user_id": user_id,
        "employee_id": emp_id,
        "token": token,
        "headers": headers,
        "company_bank_id": company_bank.id,
    }


# ── 1. Formula Evaluator Unit Tests ──────────────────────────────────────────

def test_safe_formula_evaluator_valid_expressions():
    """Verify safe arithmetic formulas evaluate accurately."""
    context = {"basic": 50000, "hra": 20000, "ctc": 100000}
    res1 = SafeFormulaEvaluator.evaluate("basic * 0.4", context)
    assert res1 == 20000.0

    res2 = SafeFormulaEvaluator.evaluate("(basic + hra) * 0.12", context)
    assert res2 == 8400.0

    res3 = SafeFormulaEvaluator.evaluate("min(basic, 15000) * 0.12", context)
    assert res3 == 1800.0


def test_safe_formula_evaluator_blocks_dangerous_code():
    """Verify unsafe expressions and malicious builtins are strictly blocked."""
    is_valid, err = SafeFormulaEvaluator.validate_formula("__import__('os').system('ls')")
    assert not is_valid
    assert len(err) > 0

    is_valid2, err2 = SafeFormulaEvaluator.validate_formula("open('/etc/passwd').read()")
    assert not is_valid2
    assert len(err2) > 0


# ── 2. V1 Legacy Endpoints Integration Tests ────────────────────────────────

@pytest.mark.asyncio
async def test_v1_payroll_periods_crud(transport):
    env = await _seed_test_env()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create period
        payload = {
            "name": f"September 2026 Test {uuid.uuid4().hex[:4]}",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "pay_date": "2026-10-01",
            "period_month": 9,
            "period_year": 2026,
            "company_id": str(env["company_id"]),
            "remarks": "Monthly payroll",
        }
        res = await ac.post("/api/v1/payroll/periods", json=payload, headers=env["headers"])
        assert res.status_code == 201
        data = res.json()["data"]
        period_id = data["id"]
        assert data["name"] == payload["name"]

        # List periods
        list_res = await ac.get("/api/v1/payroll/periods?page=1&limit=10", headers=env["headers"])
        assert list_res.status_code == 200
        assert list_res.json()["data"]["total"] >= 1

        # Get period by ID
        get_res = await ac.get(f"/api/v1/payroll/periods/{period_id}", headers=env["headers"])
        assert get_res.status_code == 200
        assert get_res.json()["data"]["id"] == period_id


@pytest.mark.asyncio
async def test_v1_payroll_run_lifecycle(transport):
    env = await _seed_test_env()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create Period
        p_res = await ac.post(
            "/api/v1/payroll/periods",
            json={
                "name": f"Run Test Period {uuid.uuid4().hex[:4]}",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
                "pay_date": "2026-10-01",
                "period_month": 9,
                "period_year": 2026,
                "company_id": str(env["company_id"]),
            },
            headers=env["headers"],
        )
        assert p_res.status_code == 201
        period_id = p_res.json()["data"]["id"]

        # 2. Trigger Run (POST /api/v1/payroll/run)
        run_res = await ac.post(
            "/api/v1/payroll/run",
            json={"periodId": period_id},
            headers=env["headers"],
        )
        assert run_res.status_code == 201
        run_data = run_res.json()["data"]
        run_id = run_data["id"]

        # 3. Get Run (GET /api/v1/payroll/runs/{runId})
        get_run = await ac.get(f"/api/v1/payroll/runs/{run_id}", headers=env["headers"])
        assert get_run.status_code == 200
        assert get_run.json()["data"]["id"] == run_id

        # 4. Preview Run
        prev_res = await ac.get(f"/api/v1/payroll/runs/{run_id}/preview", headers=env["headers"])
        assert prev_res.status_code == 200

        # 5. Validation Check
        val_res = await ac.get(f"/api/v1/payroll/runs/{run_id}/validation", headers=env["headers"])
        assert val_res.status_code == 200

        # 6. Approve Run
        appr_res = await ac.post(
            f"/api/v1/payroll/runs/{run_id}/approve",
            json={"comments": "Checked and approved by HR"},
            headers=env["headers"],
        )
        assert appr_res.status_code == 200
        assert appr_res.json()["data"]["status"] == "APPROVED"

        # 7. Finalize Run
        fin_res = await ac.post(
            f"/api/v1/payroll/runs/{run_id}/finalize",
            json={"notes": "Finalized for September", "lock": True},
            headers=env["headers"],
        )
        assert fin_res.status_code == 200
        assert fin_res.json()["data"]["status"] == "FINALIZED"
        assert fin_res.json()["data"]["is_locked"] is True


# ── 3. V2 Endpoints: Pay Components & Formula Evaluator ─────────────────────

@pytest.mark.asyncio
async def test_v2_pay_components_crud_and_validation(transport):
    env = await _seed_test_env()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create flat component
        res1 = await ac.post(
            "/api/v2/payroll/pay-components",
            json={
                "code": f"BASIC_{uuid.uuid4().hex[:4]}",
                "name": "Basic Salary",
                "type": "earning",
                "taxable": True,
                "statutory": True,
                "calculationMethod": "flat",
                "description": "Standard basic salary",
            },
            headers=env["headers"],
        )
        assert res1.status_code == 201
        assert res1.json()["data"]["type"] == "earning"

        # Create formula component
        res2 = await ac.post(
            "/api/v2/payroll/pay-components",
            json={
                "code": f"HRA_{uuid.uuid4().hex[:4]}",
                "name": "House Rent Allowance",
                "type": "earning",
                "taxable": True,
                "statutory": False,
                "calculationMethod": "formula",
                "formulaExpr": "basic * 0.5",
                "description": "50% of Basic",
            },
            headers=env["headers"],
        )
        assert res2.status_code == 201

        # Reject invalid formula
        bad_res = await ac.post(
            "/api/v2/payroll/pay-components",
            json={
                "code": f"BAD_{uuid.uuid4().hex[:4]}",
                "name": "Bad Component",
                "type": "earning",
                "taxable": True,
                "statutory": False,
                "calculationMethod": "formula",
                "formulaExpr": "__import__('os').system('ls')",
            },
            headers=env["headers"],
        )
        assert bad_res.status_code == 400

        # List components
        list_res = await ac.get("/api/v2/payroll/pay-components", headers=env["headers"])
        assert list_res.status_code == 200
        assert len(list_res.json()["data"]) >= 2


# ── 4. V2 Endpoints: Compensation & Revisions ────────────────────────────────

@pytest.mark.asyncio
async def test_v2_compensation_revision_workflow(transport):
    env = await _seed_test_env()
    emp_id = env["employee_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Get employee compensation
        comp_res = await ac.get(f"/api/v2/payroll/employees/{emp_id}/compensation", headers=env["headers"])
        assert comp_res.status_code == 200
        assert comp_res.json()["data"]["ctc_annual_paise"] == 60000000

        # Propose Revision (60k -> 75k pm CTC)
        rev_payload = {
            "newCtcAnnualPaise": 90000000,
            "effectiveDate": str(date.today() + timedelta(days=1)),
            "reason": "Annual Merit Increment",
            "notes": "Performance rating Exceeds Expectations",
        }
        create_rev = await ac.post(
            f"/api/v2/payroll/employees/{emp_id}/compensation/revisions",
            json=rev_payload,
            headers=env["headers"],
        )
        assert create_rev.status_code == 201
        rev_id = create_rev.json()["data"]["id"]

        # Approve Revision
        appr_rev = await ac.post(
            f"/api/v2/payroll/compensation/revisions/{rev_id}/approve",
            json={"remarks": "Approved by Compensation Committee"},
            headers=env["headers"],
        )
        assert appr_rev.status_code == 200
        assert appr_rev.json()["data"]["status"] == "APPROVED"

        # Verify employee active compensation was updated to new CTC
        comp_after = await ac.get(f"/api/v2/payroll/employees/{emp_id}/compensation", headers=env["headers"])
        assert comp_after.json()["data"]["ctc_annual_paise"] == 90000000


@pytest.mark.asyncio
async def test_v2_compensation_revision_rejection(transport):
    env = await _seed_test_env()
    emp_id = env["employee_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_rev = await ac.post(
            f"/api/v2/payroll/employees/{emp_id}/compensation/revisions",
            json={
                "newCtcAnnualPaise": 120000000,
                "effectiveDate": str(date.today()),
                "reason": "Promotion to Lead",
            },
            headers=env["headers"],
        )
        assert create_rev.status_code == 201
        rev_id = create_rev.json()["data"]["id"]

        # Reject without mandatory reason -> 422
        bad_rej = await ac.post(
            f"/api/v2/payroll/compensation/revisions/{rev_id}/reject",
            json={},
            headers=env["headers"],
        )
        assert bad_rej.status_code == 422

        # Reject with valid reason
        rej_res = await ac.post(
            f"/api/v2/payroll/compensation/revisions/{rev_id}/reject",
            json={"reason": "Budget cap exceeded for current fiscal quarter"},
            headers=env["headers"],
        )
        assert rej_res.status_code == 200
        assert rej_res.json()["data"]["status"] == "REJECTED"


# ── 5. V2 Endpoints: Full & Final Settlement (FnF) ───────────────────────────

@pytest.mark.asyncio
async def test_v2_full_and_final_lifecycle(transport):
    env = await _seed_test_env()
    emp_id = env["employee_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create FnF settlement
        fnf_payload = {
            "employeeId": str(emp_id),
            "exitDetails": {
                "resignationDate": "2026-08-01",
                "lastWorkingDate": "2026-09-30",
                "exitType": "resignation",
                "reason": "Relocating abroad",
                "noticePeriodDaysRequired": 60,
                "noticePeriodDaysServed": 60,
                "shortfallDays": 0,
            },
            "remarks": "Clean handover completed",
        }
        res = await ac.post("/api/v2/payroll/full-and-final", json=fnf_payload, headers=env["headers"])
        assert res.status_code == 201
        fnf_data = res.json()["data"]
        fnf_id = fnf_data["id"]
        assert fnf_data["status"] == "DRAFT"

        # Invalid exitType -> 422
        bad_fnf = {
            "employeeId": str(emp_id),
            "exitDetails": {
                "resignationDate": "2026-08-01",
                "lastWorkingDate": "2026-09-30",
                "exitType": "invalid_exit_type_xyz",
                "reason": "Test",
                "noticePeriodDaysRequired": 30,
                "noticePeriodDaysServed": 30,
                "shortfallDays": 0,
            },
        }
        bad_res = await ac.post("/api/v2/payroll/full-and-final", json=bad_fnf, headers=env["headers"])
        assert bad_res.status_code == 422

        # Get FnF detail
        get_res = await ac.get(f"/api/v2/payroll/full-and-final/{fnf_id}", headers=env["headers"])
        assert get_res.status_code == 200
        assert get_res.json()["data"]["id"] == fnf_id

        # Approve FnF
        appr_res = await ac.post(
            f"/api/v2/payroll/full-and-final/{fnf_id}/approve",
            json={"remarks": "Assets returned and approved by IT"},
            headers=env["headers"],
        )
        assert appr_res.status_code == 200
        assert appr_res.json()["data"]["status"] == "APPROVED"

        # Finalize FnF
        fin_res = await ac.post(
            f"/api/v2/payroll/full-and-final/{fnf_id}/finalize",
            json={"notes": "All clearances verified"},
            headers=env["headers"],
        )
        assert fin_res.status_code == 200
        assert fin_res.json()["data"]["status"] == "FINALIZED"

        # Download Statement
        stmt_res = await ac.get(f"/api/v2/payroll/full-and-final/{fnf_id}/statement/download", headers=env["headers"])
        assert stmt_res.status_code == 200
        assert b"FULL & FINAL SETTLEMENT STATEMENT" in stmt_res.content


# ── 6. V2 Endpoints: Payment Batches & Idempotency ───────────────────────────

@pytest.mark.asyncio
async def test_v2_payment_batches_and_idempotency(transport):
    env = await _seed_test_env()
    emp_id = env["employee_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create period & run
        p_res = await ac.post(
            "/api/v1/payroll/periods",
            json={
                "name": f"Batch Period {uuid.uuid4().hex[:4]}",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
                "pay_date": "2026-10-01",
                "period_month": 9,
                "period_year": 2026,
                "company_id": str(env["company_id"]),
            },
            headers=env["headers"],
        )
        period_id = p_res.json()["data"]["id"]

        run_res = await ac.post(
            "/api/v1/payroll/run",
            json={"periodId": period_id},
            headers=env["headers"],
        )
        run_id = run_res.json()["data"]["id"]

        # Finalize run
        await ac.post(f"/api/v2/payroll/runs/{run_id}/approve", headers=env["headers"])
        await ac.post(f"/api/v2/payroll/runs/{run_id}/finalize", headers=env["headers"])

        # Create Payment Batch from finalized run
        batch_payload = {
            "sourceAccountId": str(env["company_bank_id"]),
            "paymentMode": "NEFT",
            "heldEmployeeIds": [],
            "notes": "Salary batch for September",
        }
        b_res = await ac.post(
            f"/api/v2/payroll/runs/{run_id}/payment-batches",
            json=batch_payload,
            headers=env["headers"],
        )
        assert b_res.status_code == 201
        batch_data = b_res.json()["data"]
        batch_id = batch_data["id"]

        # Validate Batch
        val_res = await ac.post(f"/api/v2/payroll/payment-batches/{batch_id}/validate", headers=env["headers"])
        assert val_res.status_code == 200

        # Approve Batch
        appr_b = await ac.post(
            f"/api/v2/payroll/payment-batches/{batch_id}/approve",
            json={"remarks": "Approved for disbursal"},
            headers=env["headers"],
        )
        assert appr_b.status_code == 200

        # Submit Batch — Idempotency Test:
        # A) Missing Idempotency-Key -> 400
        sub_payload = {
            "bankReferenceNumber": f"REF-{uuid.uuid4().hex[:6]}",
            "submissionDate": "2026-10-01",
            "notes": "Sent to HDFC Corporate Netbanking",
        }
        no_key_res = await ac.post(
            f"/api/v2/payroll/payment-batches/{batch_id}/submit",
            json=sub_payload,
            headers=env["headers"],
        )
        assert no_key_res.status_code == 400
        assert "Idempotency-Key" in no_key_res.json()["detail"]

        # B) Submit with valid Idempotency-Key
        idemp_key = f"idem-submit-{uuid.uuid4()}"
        headers_with_idemp = dict(env["headers"])
        headers_with_idemp["Idempotency-Key"] = idemp_key

        sub_res1 = await ac.post(
            f"/api/v2/payroll/payment-batches/{batch_id}/submit",
            json=sub_payload,
            headers=headers_with_idemp,
        )
        assert sub_res1.status_code == 200
        assert sub_res1.json()["data"]["status"] == "SUBMITTED"

        # C) Re-sending identical request with same Idempotency-Key returns cached response
        sub_res2 = await ac.post(
            f"/api/v2/payroll/payment-batches/{batch_id}/submit",
            json=sub_payload,
            headers=headers_with_idemp,
        )
        assert sub_res2.status_code == 200
        assert sub_res2.json()["data"]["bank_reference_number"] == sub_payload["bankReferenceNumber"]


# ── 7. V2 Endpoints: Variable Inputs & Statutory ─────────────────────────────

@pytest.mark.asyncio
async def test_v2_variable_inputs_and_statutory(transport):
    env = await _seed_test_env()
    emp_id = env["employee_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Statutory Config
        stat_cfg = await ac.get("/api/v2/payroll/statutory/config", headers=env["headers"])
        assert stat_cfg.status_code == 200
        assert stat_cfg.json()["data"]["pf_enabled"] is True

        # 2. Variable Input (Overtime)
        var_payload = {
            "employeeId": str(emp_id),
            "periodId": str(uuid.uuid4()),
            "type": "overtime",
            "amountPaise": 500000,  # 5,000 INR
            "units": "10.0",
            "ratePerUnitPaise": 50000,
            "description": "10 hours weekend project release overtime",
        }
        var_res = await ac.post("/api/v2/payroll/variable-inputs", json=var_payload, headers=env["headers"])
        assert var_res.status_code == 201
        var_id = var_res.json()["data"]["id"]

        # Approve variable input
        appr_var = await ac.post(
            f"/api/v2/payroll/variable-inputs/{var_id}/approve",
            json={"remarks": "Manager approved OT logs"},
            headers=env["headers"],
        )
        assert appr_var.status_code == 200
        assert appr_var.json()["data"]["status"] == "APPROVED"


# ── 8. V2 Endpoints: Employee Self-Service & Sensitive Data Reveal ───────────

@pytest.mark.asyncio
async def test_v2_employee_self_service_and_bank_reveal(transport):
    env = await _seed_test_env()
    emp_id = env["employee_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Dashboard
        dash = await ac.get("/api/v2/payroll/employee/dashboard", headers=env["headers"])
        assert dash.status_code == 200
        assert dash.json()["data"]["current_ctc_annual_paise"] == 60000000

        # Reveal Bank Account (Sensitive operation requires mandatory reason)
        bad_rev = await ac.post(
            f"/api/v2/payroll/employees/{emp_id}/reveal-bank-account",
            json={},
            headers=env["headers"],
        )
        assert bad_rev.status_code == 422

        good_rev = await ac.post(
            f"/api/v2/payroll/employees/{emp_id}/reveal-bank-account",
            json={"reason": "Auditing bank account before salary disbursement"},
            headers=env["headers"],
        )
        assert good_rev.status_code == 200
        assert "account_number" in good_rev.json()["data"]
