"""End-to-end backend verification for Payroll v2 Payment Batches & Disbursements."""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

sys.path.insert(0, os.getcwd())

from app.core.security import hash_password
from app.db.database import AsyncSessionLocal
from app.main import create_app
from app.models.company import Company
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.payroll import PayCycle, PayrollAuditLog, PayrollRun, Payslip
from app.models.payroll_models import (
    CompanyBankAccount,
    PaymentBatch,
    PaymentBatchBankFile,
    PaymentBatchItem,
    PayrollPeriod,
    PayrollRunEmployee,
)
from app.models.user import User, UserAccountStatus, UserRole
from app.utils.jwt import create_access_token


@pytest.fixture
def app_instance():
    return create_app()


@pytest.fixture
def transport(app_instance):
    return ASGITransport(app=app_instance)


async def _seed_payment_fixture():
    """Seed an isolated tenant, maker, checker, 2 employees with bank accounts, and a finalized locked run."""
    company_id = uuid.uuid4()
    other_company_id = uuid.uuid4()
    maker_id = uuid.uuid4()
    checker_id = uuid.uuid4()
    super_admin_id = uuid.uuid4()
    emp1_id = uuid.uuid4()
    emp2_id = uuid.uuid4()
    bank_acc_id = uuid.uuid4()
    period_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        db.add(Company(id=company_id, name=f"PayTest Co {company_id.hex[:6]}"))
        db.add(Company(id=other_company_id, name=f"Other Co {other_company_id.hex[:6]}"))

        maker = User(
            id=maker_id,
            company_id=company_id,
            name="Payroll Maker",
            email=f"maker_{maker_id.hex[:6]}@example.com",
            phone=f"98{maker_id.int % 100000000:08d}",
            password_hash=hash_password("Pass@1234"),
            role=UserRole.HR_ADMIN,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
        )
        checker = User(
            id=checker_id,
            company_id=company_id,
            name="Finance Checker",
            email=f"checker_{checker_id.hex[:6]}@example.com",
            phone=f"97{checker_id.int % 100000000:08d}",
            password_hash=hash_password("Pass@1234"),
            role=UserRole.EXECUTIVE,
            account_status=UserAccountStatus.ACTIVE.value,
            is_active=True,
        )
        existing_sa = (
            await db.execute(select(User).where(User.email == "superadmin@ofc360.com").limit(1))
        ).scalar_one_or_none()
        created_sa_id = None
        if existing_sa is not None:
            sa_id = existing_sa.id
            sa_email = existing_sa.email
            db.add_all([maker, checker])
        else:
            sa_id = super_admin_id
            sa_email = "superadmin@ofc360.com"
            created_sa_id = super_admin_id
            super_admin = User(
                id=super_admin_id,
                company_id=None,
                name="Platform Owner",
                email=sa_email,
                phone=f"96{super_admin_id.int % 100000000:08d}",
                password_hash=hash_password("Pass@1234"),
                role=UserRole.SUPER_ADMIN,
                account_status=UserAccountStatus.ACTIVE.value,
                is_active=True,
            )
            db.add_all([maker, checker, super_admin])

        e1 = Employee(
            id=emp1_id,
            company_id=company_id,
            employee_id=f"EMP-{emp1_id.hex[:4].upper()}",
            first_name="Ananya",
            last_name="Verma",
            personal_email=f"e1_{emp1_id.hex[:6]}@example.com",
            phone=f"95{emp1_id.int % 100000000:08d}",
            department="Engineering",
            designation="Staff Engineer",
            joining_date=date(2023, 1, 1),
            status="ACTIVE",
            is_active=True,
        )
        e2 = Employee(
            id=emp2_id,
            company_id=company_id,
            employee_id=f"EMP-{emp2_id.hex[:4].upper()}",
            first_name="Vikram",
            last_name="Nair",
            personal_email=f"e2_{emp2_id.hex[:6]}@example.com",
            phone=f"94{emp2_id.int % 100000000:08d}",
            department="Finance",
            designation="Analyst",
            joining_date=date(2023, 3, 1),
            status="ACTIVE",
            is_active=True,
        )
        db.add_all([e1, e2])

        db.add_all([
            EmployeeBankAccount(
                id=uuid.uuid4(),
                employee_id=emp1_id,
                account_holder_name="Ananya Verma",
                bank_name="HDFC Bank",
                account_number="50100012345678",
                ifsc_code="HDFC0000512",
                is_primary=True,
            ),
            EmployeeBankAccount(
                id=uuid.uuid4(),
                employee_id=emp2_id,
                account_holder_name="Vikram Nair",
                bank_name="ICICI Bank",
                account_number="000401556677",
                ifsc_code="ICIC0000004",
                is_primary=True,
            ),
        ])

        db.add(
            CompanyBankAccount(
                id=bank_acc_id,
                company_id=company_id,
                bank_name="HDFC Bank",
                account_number="50200011221740",
                ifsc_code="HDFC0000512",
                account_holder_name="PayTest Co Pvt Ltd",
                account_type="CURRENT",
                is_primary=True,
                is_active=True,
            )
        )

        db.add(
            PayCycle(
                id=cycle_id,
                company_id=company_id,
                name="Monthly",
                frequency="MONTHLY",
                is_active=True,
            )
        )
        db.add(
            PayrollPeriod(
                id=period_id,
                company_id=company_id,
                pay_cycle_id=cycle_id,
                name="November 2026",
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                pay_date=date(2026, 12, 1),
                period_month=11,
                period_year=2026,
                status="LOCKED",
                is_locked=True,
            )
        )
        db.add(
            PayrollRun(
                id=run_id,
                company_id=company_id,
                period_id=period_id,
                pay_cycle_id=cycle_id,
                run_number=f"PR-202611-{run_id.hex[:4].upper()}",
                period_month=11,
                period_year=2026,
                status="FINALIZED",
                is_locked=True,
                total_employees=2,
                total_gross_paise=25000000,
                total_deductions_paise=3000000,
                total_net_paise=22000000,
                finalized_at=datetime.now(timezone.utc),
            )
        )
        db.add_all([
            PayrollRunEmployee(
                id=uuid.uuid4(),
                company_id=company_id,
                run_id=run_id,
                employee_id=emp1_id,
                gross_pay_paise=15000000,
                deductions_paise=2000000,
                net_pay_paise=13000000,
                status="FINALIZED",
            ),
            PayrollRunEmployee(
                id=uuid.uuid4(),
                company_id=company_id,
                run_id=run_id,
                employee_id=emp2_id,
                gross_pay_paise=10000000,
                deductions_paise=1000000,
                net_pay_paise=9000000,
                status="FINALIZED",
            ),
        ])
        await db.commit()

    maker_token = create_access_token(
        user_id=maker_id, role=UserRole.HR_ADMIN.value, company_id=company_id, email=f"maker_{maker_id.hex[:6]}@example.com"
    )
    checker_token = create_access_token(
        user_id=checker_id, role=UserRole.EXECUTIVE.value, company_id=company_id, email=f"checker_{checker_id.hex[:6]}@example.com"
    )
    other_token = create_access_token(
        user_id=uuid.uuid4(), role=UserRole.HR_ADMIN.value, company_id=other_company_id, email="other@example.com"
    )
    sa_token = create_access_token(
        user_id=sa_id, role=UserRole.SUPER_ADMIN.value, company_id=None, email=sa_email
    )

    return {
        "company_id": company_id,
        "other_company_id": other_company_id,
        "created_sa_id": created_sa_id,
        "run_id": run_id,
        "period_id": period_id,
        "bank_acc_id": bank_acc_id,
        "emp1_id": emp1_id,
        "emp2_id": emp2_id,
        "maker_headers": {"Authorization": f"Bearer {maker_token}"},
        "checker_headers": {"Authorization": f"Bearer {checker_token}"},
        "other_headers": {"Authorization": f"Bearer {other_token}"},
        "sa_headers": {"Authorization": f"Bearer {sa_token}"},
    }


async def _cleanup_company_data(company_ids: list[uuid.UUID], created_sa_id: uuid.UUID | None = None):
    async with AsyncSessionLocal() as db:
        for cid in company_ids:
            await db.execute(delete(PaymentBatchItem).where(PaymentBatchItem.company_id == cid))
            await db.execute(delete(PaymentBatchBankFile).where(PaymentBatchBankFile.company_id == cid))
            await db.execute(delete(PaymentBatch).where(PaymentBatch.company_id == cid))
            await db.execute(delete(PayrollAuditLog).where(PayrollAuditLog.company_id == cid))
            await db.execute(delete(Payslip).where(Payslip.company_id == cid))
            await db.execute(delete(PayrollRunEmployee).where(PayrollRunEmployee.company_id == cid))
            await db.execute(delete(PayrollRun).where(PayrollRun.company_id == cid))
            await db.execute(delete(PayrollPeriod).where(PayrollPeriod.company_id == cid))
            await db.execute(delete(PayCycle).where(PayCycle.company_id == cid))
            await db.execute(delete(CompanyBankAccount).where(CompanyBankAccount.company_id == cid))
            await db.execute(delete(EmployeeBankAccount).where(EmployeeBankAccount.company_id == cid))
            await db.execute(delete(Employee).where(Employee.company_id == cid))
            await db.execute(delete(User).where(User.company_id == cid))
            await db.execute(delete(Company).where(Company.id == cid))
        if created_sa_id is not None:
            await db.execute(delete(User).where(User.id == created_sa_id))
        await db.commit()


@pytest.mark.asyncio
async def test_payment_batch_complete_lifecycle_summary_and_security(transport):
    env = await _seed_payment_fixture()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Super Admin strictly blocked (403)
            sa_res = await ac.get("/api/v2/payroll/payment-batches/summary", headers=env["sa_headers"])
            assert sa_res.status_code == 403

            # 2. Eligible runs returns the finalized locked run prior to batch creation
            el_res = await ac.get("/api/v2/payroll/payment-batches/eligible-runs", headers=env["maker_headers"])
            assert el_res.status_code == 200
            assert len(el_res.json()["data"]) == 1
            assert el_res.json()["data"][0]["id"] == str(env["run_id"])

            # 3. Payment modes & tenant bank accounts
            modes_res = await ac.get("/api/v2/payroll/payment-modes", headers=env["maker_headers"])
            assert modes_res.status_code == 200
            assert any(m["code"] == "NEFT" and m["enabled"] for m in modes_res.json()["data"])

            bank_res = await ac.get("/api/v2/payroll/company-bank-accounts", headers=env["maker_headers"])
            assert bank_res.status_code == 200
            assert bank_res.json()["data"][0]["account_number_masked"].endswith("1740")

            # 4. Create batch via direct POST /payment-batches
            create_res = await ac.post(
                "/api/v2/payroll/payment-batches",
                json={
                    "runId": str(env["run_id"]),
                    "sourceAccountId": str(env["bank_acc_id"]),
                    "paymentMode": "NEFT",
                    "notes": "Initial November salary payout",
                },
                headers=env["maker_headers"],
            )
            assert create_res.status_code == 201
            batch = create_res.json()["data"]
            batch_id = batch["id"]
            assert batch["period_name"] == "November 2026"
            assert batch["employee_count"] == 2
            assert batch["payable_amount_paise"] == 22000000
            assert batch["status"] == "DRAFT"

            # 5. Update draft batch instructions
            patch_res = await ac.patch(
                f"/api/v2/payroll/payment-batches/{batch_id}",
                json={"paymentMode": "RTGS", "notes": "Switched to RTGS"},
                headers=env["maker_headers"],
            )
            assert patch_res.status_code == 200
            assert patch_res.json()["data"]["payment_mode"] == "RTGS"

            # 6. Validate (read-only check first, then mutating validate -> VALIDATED)
            ro_val = await ac.get(f"/api/v2/payroll/payment-batches/{batch_id}/validation", headers=env["maker_headers"])
            assert ro_val.status_code == 200
            assert ro_val.json()["data"]["has_blocking_errors"] is False

            val_res = await ac.post(f"/api/v2/payroll/payment-batches/{batch_id}/validate", headers=env["maker_headers"])
            assert val_res.status_code == 200
            assert val_res.json()["data"]["batch_status"] == "VALIDATED"

            # 7. Submit for approval -> summary reflects pending_approval
            sub_ap_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/submit-for-approval",
                json={"remarks": "Ready for checker review"},
                headers=env["maker_headers"],
            )
            assert sub_ap_res.status_code == 200
            assert sub_ap_res.json()["data"]["status"] == "PENDING_APPROVAL"

            sum_res = await ac.get("/api/v2/payroll/payment-batches/summary", headers=env["maker_headers"])
            assert sum_res.status_code == 200
            assert sum_res.json()["data"]["total_batches"] == 1
            assert sum_res.json()["data"]["awaiting_approval_batches"] == 1

            # 8. Maker cannot self-approve (403); independent checker approves (200)
            self_ap = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/approve",
                json={"remarks": "Self attempt"},
                headers=env["maker_headers"],
            )
            assert self_ap.status_code == 403

            ap_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/approve",
                json={"remarks": "Verified totals and bank split"},
                headers=env["checker_headers"],
            )
            assert ap_res.status_code == 200
            assert ap_res.json()["data"]["status"] == "APPROVED"

            # 9. Cross-tenant isolation strictly returns 404
            iso_res = await ac.get(f"/api/v2/payroll/payment-batches/{batch_id}", headers=env["other_headers"])
            assert iso_res.status_code == 404

            # 10. Generate & download bank file synchronously
            bf_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/bank-file",
                json={"format": "HDFC_ENET_CSV"},
                headers=env["maker_headers"],
            )
            assert bf_res.status_code == 200
            assert bf_res.json()["data"]["file_name"].endswith("_HDFC_ENET_CSV.csv")

            dl_res = await ac.get(
                f"/api/v2/payroll/payment-batches/{batch_id}/bank-file/download",
                headers=env["maker_headers"],
            )
            assert dl_res.status_code == 200
            assert b"Beneficiary_Account" in dl_res.content

            # 11. Submit to bank requires Idempotency-Key
            no_idem = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/submit",
                json={"bankReferenceNumber": "HDFC-2026-991", "submissionDate": "2026-11-28T10:30:00Z"},
                headers=env["maker_headers"],
            )
            assert no_idem.status_code == 400

            sub_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/submit",
                json={"bankReferenceNumber": "HDFC-2026-991", "submissionDate": "2026-11-28T10:30:00Z"},
                headers={**env["maker_headers"], "Idempotency-Key": str(uuid.uuid4())},
            )
            assert sub_res.status_code == 200
            assert sub_res.json()["data"]["status"] == "SUBMITTED"

            # Search & filter verification
            search_res = await ac.get(
                "/api/v2/payroll/payment-batches?search=November+2026&status=submitted",
                headers=env["maker_headers"],
            )
            assert search_res.status_code == 200
            assert search_res.json()["data"]["total"] == 1

            # 12. Record partial outcome: 1 PAID (UTR), 1 FAILED -> create retry batch for only the FAILED item
            detail = (await ac.get(f"/api/v2/payroll/payment-batches/{batch_id}", headers=env["maker_headers"])).json()["data"]
            items_list = detail["items"]["items"]
            assert len(items_list) == 2
            assert all("account_number" not in it and str(it["account_number_masked"]).startswith("•") for it in items_list)

            rec_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/record-results",
                json={
                    "results": [
                        {"itemId": items_list[0]["id"], "status": "PAID", "utrNumber": "UTR-SUCCESS-001"},
                        {"itemId": items_list[1]["id"], "status": "FAILED", "errorMessage": "Account frozen"},
                    ]
                },
                headers=env["maker_headers"],
            )
            assert rec_res.status_code == 200
            assert rec_res.json()["data"]["status"] == "PARTIAL"

            # Reconcile parent batch
            recon_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/reconcile",
                json={"notes": "Reconciled with 1 partial failure"},
                headers=env["maker_headers"],
            )
            assert recon_res.status_code == 200
            recon_data = recon_res.json()["data"]
            assert recon_data["is_reconciled"] is True
            assert recon_data["mismatch_paise"] == 0

            # Retry failed creates linked DRAFT batch containing ONLY the 1 failed employee
            retry_res = await ac.post(
                f"/api/v2/payroll/payment-batches/{batch_id}/retry-failed",
                json={"reason": "Employee resolved frozen account"},
                headers=env["maker_headers"],
            )
            assert retry_res.status_code == 200
            retry_batch = retry_res.json()["data"]
            assert retry_batch["status"] == "DRAFT"
            assert retry_batch["employee_count"] == 1
            assert retry_batch["retry_of_batch_id"] == batch_id

            # Deleting draft retry batch releases parent failure cleanly & removes draft
            del_res = await ac.delete(
                f"/api/v2/payroll/payment-batches/{retry_batch['id']}",
                headers=env["maker_headers"],
            )
            assert del_res.status_code == 200
            assert del_res.json()["data"]["deleted"] is True

            # Export report, reconciliation report, & audit logs
            exp_res = await ac.get(f"/api/v2/payroll/payment-batches/{batch_id}/export", headers=env["maker_headers"])
            assert exp_res.status_code == 200
            assert b"UTR-SUCCESS-001" in exp_res.content

            rec_exp_res = await ac.get(
                f"/api/v2/payroll/payment-batches/{batch_id}/reconciliation/export",
                headers=env["maker_headers"],
            )
            assert rec_exp_res.status_code == 200
            assert b"OFC360 PAYMENT RECONCILIATION REPORT" in rec_exp_res.content

            logs_res = await ac.get(f"/api/v2/payroll/payment-batches/{batch_id}/audit-logs", headers=env["maker_headers"])
            assert logs_res.status_code == 200
            assert len(logs_res.json()["data"]) >= 5
    finally:
        await _cleanup_company_data(
            [env["company_id"], env["other_company_id"]],
            created_sa_id=env.get("created_sa_id"),
        )
