"""Batch 5 focused service tests (SQLite; no external providers or seed data)."""
from __future__ import annotations

import calendar
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("ENVIRONMENT", "local")

from app.db.base import Base
import app.models  # noqa: F401 - register all production metadata
from app.attendance.models.attendance import Attendance
from app.models.company import Branch, Company, EntityPayrollCalendar, LegalEntity
from app.models.employee import Employee
from app.models.employee_policy_acceptance import PolicyAcknowledgementAssignment
from app.models.grievance_posh import POSHComplaint
from app.models.leave import LeaveRequest
from app.models.leave_balance import LeaveBalance
from app.models.mobile_pwa import MobileIdempotencyRecord
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_compliance import ComplianceDueDate, PayrollCompliance
from app.models.payroll_models import (
    PaymentBatch, PaymentBatchItem, PayrollPeriod, PayrollRunEmployee, VariableInput,
)
from app.models.user import User
from app.services.compliance_monitor_service import ComplianceMonitorService
from app.services.grievance_posh_service import ConfidentialityError, GrievancePOSHService
from app.services.mobile_pwa_service import MobilePWAService
from app.services.payroll.payment_batch_service import PaymentBatchService
from app.services.payroll.run_service import PayrollRunService
from app.services.payroll.statutory_service import StatutoryService
from app.services.policy_service import PolicyGovernanceService
from app.services.whatsapp_bot_service import WhatsAppBotService


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kwargs):
    return "JSON"


TEST_TABLES = [
    "companies", "users", "legal_entities", "branches", "employees", "employee_bank_accounts",
    "salary_structures", "compensations", "payroll_periods", "payroll_runs", "pay_cycles",
    "payroll_run_employees", "payslips", "variable_inputs", "payment_batches",
    "payment_batch_items", "payment_batch_bank_files", "payroll_audit_logs",
    "leave_balances", "leave_requests", "employee_leave_policies",
    "whatsapp_inbound_messages", "whatsapp_conversations", "mobile_idempotency_records",
    "mobile_push_subscriptions", "grievance_cases", "grievance_case_events",
    "posh_icc_committees", "posh_icc_members", "posh_complaints", "posh_evidence_vault",
    "posh_training_records", "posh_annual_returns", "company_policy_documents",
    "employee_policy_acceptances", "policy_acknowledgement_assignments", "user_notifications", "attendances",
    "entity_payroll_calendars", "employee_entity_transfers", "payroll_compliance",
    "payroll_compliance_due_dates", "payroll_compliance_challans",
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [Base.metadata.tables[name] for name in TEST_TABLES]
    # Compile the production PostgreSQL metadata for SQLite without maintaining a
    # parallel test schema. JSONB cast defaults and duplicate index names are the
    # only temporary adaptations, matching the established repository fixture.
    import re
    from sqlalchemy import text
    default_restore, index_restore = [], []
    seen_indexes = set()
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
    company = Company(id=uuid.uuid4(), name="Batch 5 Test Pvt Ltd")
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company, prefix="employee", role="employee") -> User:
    unique = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(), company_id=company.id, name=f"{prefix.title()} User",
        email=f"{prefix}-{unique}@example.com", phone=str(int(unique, 16))[:10].ljust(10, "1"),
        password_hash="test-only-hash", role=role, is_active=True, is_verified=True,
        account_status="ACTIVE",
    )
    db.add(user)
    await db.flush()
    return user


async def _employee(
    db: AsyncSession, company: Company, user: User | None = None, *,
    legal_entity_id=None, branch_id=None, branch=None, department="Engineering",
    employment_type="FULL_TIME",
) -> Employee:
    unique = uuid.uuid4().hex[:8]
    employee = Employee(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id if user else None,
        employee_id=f"EMP-{unique}", first_name="Real", last_name="Employee",
        personal_email=f"employee-{unique}@example.com", phone="9876543210",
        department=department, designation="Engineer", joining_date=date(2020, 1, 1),
        employment_type=employment_type, employment_status="CONFIRMED", status="ACTIVE",
        role="employee", legal_entity_id=legal_entity_id, branch_id=branch_id, branch=branch,
        pan_number="ABCDE1234F",
    )
    db.add(employee)
    await db.flush()
    return employee


async def _entity(db: AsyncSession, company: Company, code="ENTITY-A", state="RJ") -> LegalEntity:
    entity = LegalEntity(id=uuid.uuid4(), company_id=company.id, name=code, code=code, state_code=state)
    db.add(entity)
    await db.flush()
    return entity


async def _branch(db: AsyncSession, company: Company, entity: LegalEntity, code="JAIPUR", state="RJ") -> Branch:
    branch = Branch(id=uuid.uuid4(), company_id=company.id, legal_entity_id=entity.id, name=code.title(), code=code, state_code=state)
    db.add(branch)
    await db.flush()
    return branch


async def _run(db: AsyncSession, company: Company, *, month=1, year=2026, entity_id=None) -> PayrollRun:
    run = PayrollRun(
        id=uuid.uuid4(), company_id=company.id, legal_entity_id=entity_id,
        period_month=month, period_year=year, status="APPROVED", run_number=f"PR-{uuid.uuid4().hex[:10]}",
    )
    db.add(run)
    await db.flush()
    return run


async def _payslip(db: AsyncSession, company: Company, run: PayrollRun, employee: Employee, **values) -> Payslip:
    payslip = Payslip(
        id=uuid.uuid4(), company_id=company.id, payroll_run_id=run.id, employee_id=employee.id,
        payslip_number=f"PAY-{uuid.uuid4().hex[:12]}", period_month=run.period_month,
        period_year=run.period_year, total_days_in_month=31, paid_days=Decimal("30"),
        basic=Decimal("30000"), hra=Decimal("12000"), gross_earnings=Decimal("50000"),
        employee_pf=Decimal("1800"), total_deductions=Decimal("2500"), net_pay=Decimal("47500"),
        **values,
    )
    db.add(payslip)
    await db.flush()
    return payslip


@pytest.mark.asyncio
async def test_whatsapp_commands_interactive_leave_and_webhook_dedup(db, monkeypatch):
    company = await _company(db)
    user = await _user(db, company)
    employee = await _employee(db, company, user)
    db.add(LeaveBalance(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
        leave_type="Sick Leave", year=date.today().year, allocated_days=Decimal("12"), used_days=Decimal("2"),
    ))
    await db.commit()
    monkeypatch.setattr("app.services.notification_service.notify", AsyncMock())
    sender = AsyncMock()
    service = WhatsAppBotService(db, sender=sender)

    assert "OFC360 commands" in (await service.execute_command(user, "MENU"))["text"]
    balance = (await service.execute_command(user, "LEAVE BALANCE"))["text"]
    assert "Sick Leave: 10 days" in balance
    assert "Which leave type" in (await service.execute_command(user, "LEAVE APPLY"))["text"]
    assert "start date" in (await service.execute_command(user, "Sick Leave"))["text"]
    leave_day = date.today() + timedelta(days=30)
    assert "end date" in (await service.execute_command(user, leave_day.isoformat()))["text"]
    assert "short reason" in (await service.execute_command(user, leave_day.isoformat()))["text"]
    submitted = (await service.execute_command(user, "Medical appointment"))["text"]
    assert "submitted" in submitted
    assert (await db.execute(select(func.count(LeaveRequest.id)))).scalar() == 1

    payload = {"entry": [{"changes": [{"value": {"messages": [{
        "id": "wamid.batch5", "from": user.phone, "type": "text", "text": {"body": "MENU"},
    }]}}]}]}
    first = await service.handle_inbound(payload)
    replay = await service.handle_inbound(payload)
    assert first[0]["duplicate"] is False
    assert replay[0]["duplicate"] is True
    assert sender.await_count == 1


@pytest.mark.asyncio
async def test_pwa_attendance_idempotency_replay_and_conflict(db):
    company = await _company(db)
    user = await _user(db, company)
    attendance = SimpleNamespace(
        id=uuid.uuid4(), date=date.today(), check_in_time=datetime.now(), check_out_time=None,
        status="Present", verified=True, punch_verified_by="FACE", latitude=26.9,
        longitude=75.8, location_accuracy=5.0, liveness_score=0.99, face_distance=0.2,
        working_hours=None,
    )
    checkin = SimpleNamespace(check_in_with_face_base64=AsyncMock(return_value=attendance))
    service = MobilePWAService(db, checkin_service=checkin, checkout_service=SimpleNamespace())
    values = dict(
        user_id=user.id, company_id=company.id, operation="CHECK_IN",
        idempotency_key="offline-punch-0001", image_base64="ZmFrZS1pbWFnZQ==",
        latitude=26.9, longitude=75.8, client_captured_at=datetime.now(UTC).isoformat(),
    )
    first = await service.mark_attendance(**values)
    replay = await service.mark_attendance(**values)
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert replay["attendance_id"] == first["attendance_id"]
    assert checkin.check_in_with_face_base64.await_count == 1
    ledger = (await db.execute(select(MobileIdempotencyRecord))).scalar_one()
    assert ledger.status == "COMPLETED"
    with pytest.raises(HTTPException) as exc:
        await service.mark_attendance(**{**values, "latitude": 27.1})
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_grievance_confidentiality_investigator_block_and_employee_appeal(db):
    company = await _company(db)
    reporter = await _user(db, company, "reporter")
    accused = await _user(db, company, "accused")
    investigator = await _user(db, company, "investigator")
    admin = await _user(db, company, "admin", "hr_admin")
    unrelated = await _user(db, company, "unrelated")
    service = GrievancePOSHService(db)
    case = await service.create_grievance(
        company_id=company.id, category="workplace", subject="Confidential concern",
        description="Detailed confidential report", anonymous=True, accused_user_ids=[accused.id],
        actor_id=reporter.id, sla_hours=1,
    )
    assert case.receipt_token
    serialized = service.serialize_grievance(case, include_reporter=True)
    assert serialized["reporter_user_id"] is None
    with pytest.raises(ConfidentialityError):
        await service.get_grievance(case.id, company_id=company.id, actor_id=unrelated.id)
    with pytest.raises(ConfidentialityError):
        await service.assign_investigator(case.id, company_id=company.id, investigator_id=accused.id, actor_id=admin.id, actor_role="hr_admin")
    received = await service.get_grievance(
        case.id, company_id=company.id, actor_id=unrelated.id, receipt_token=case.receipt_token,
    )
    assert received.id == case.id
    await service.assign_investigator(case.id, company_id=company.id, investigator_id=investigator.id, actor_id=admin.id, actor_role="hr_admin")
    with pytest.raises(ConfidentialityError):
        await service.resolve_grievance(
            case.id, company_id=company.id, resolution="Unauthorized resolution", actor_id=unrelated.id,
        )
    await service.resolve_grievance(
        case.id, company_id=company.id, resolution="Corrective action completed", actor_id=admin.id, actor_role="hr_admin",
    )
    with pytest.raises(ConfidentialityError):
        await service.appeal_grievance(
            case.id, company_id=company.id, reason="Anonymous appeal without a receipt",
        )
    appealed = await service.appeal_grievance(
        case.id, company_id=company.id, reason="Requesting an independent appeal review", receipt_token=case.receipt_token,
    )
    assert appealed.status == "APPEALED"
    decided = await service.decide_appeal(
        case.id, company_id=company.id, decision="UPHELD", resolution="Appeal reviewed and upheld", actor_id=admin.id, actor_role="hr_admin",
    )
    assert decided.status == "CLOSED"

    overdue = await service.create_grievance(
        company_id=company.id, category="payroll", subject="SLA test", description="Overdue case",
        reporter_user_id=reporter.id, sla_hours=1,
    )
    overdue.sla_due_at = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()
    assert await service.escalate_overdue(company_id=company.id) == 1
    assert overdue.status == "ESCALATED"


@pytest.mark.asyncio
async def test_posh_icc_quorum_90_day_inquiry_and_encrypted_evidence(db):
    company = await _company(db)
    user = await _user(db, company)
    employee = await _employee(db, company, user)
    icc_user = await _user(db, company, "icc")
    outsider = await _user(db, company, "outsider")
    service = GrievancePOSHService(db)
    members = [
        {"name": "Presiding Woman", "gender": "FEMALE", "role": "PRESIDING_OFFICER", "user_id": icc_user.id},
        {"name": "Internal Woman", "gender": "FEMALE", "role": "MEMBER"},
        {"name": "External Expert", "gender": "FEMALE", "role": "EXTERNAL_MEMBER", "is_external": True},
        {"name": "Internal Member", "gender": "MALE", "role": "MEMBER"},
    ]
    assert service.validate_icc_composition(members)["valid"] is True
    invalid = [dict(members[0], gender="MALE"), *members[1:]]
    assert service.validate_icc_composition(invalid)["valid"] is False
    committee = await service.create_icc_committee(
        company_id=company.id, name="ICC 2026", term_start=date(2026, 1, 1),
        term_end=date(2028, 12, 31), members=members,
    )
    filed_at = datetime(2026, 1, 10, 9, 30, tzinfo=UTC)
    complaint = await service.create_posh_complaint(
        company_id=company.id, committee_id=committee.id, description="Confidential POSH complaint",
        reporter_employee_id=employee.id, reporter_user_id=user.id, filed_at=filed_at,
    )
    assert complaint.inquiry_due_at == filed_at + timedelta(days=90)
    timeline = service.serialize_posh(complaint, now=filed_at)
    assert timeline["inquiry_days_remaining"] == 90
    evidence = await service.add_evidence(
        complaint.id, company_id=company.id, actor_id=user.id, file_name="evidence.txt",
        content_type="text/plain", content=b"confidential evidence",
    )
    assert b"confidential evidence" not in bytes(evidence.ciphertext)
    content, _ = await service.read_evidence(evidence.id, company_id=company.id, actor_id=user.id)
    assert content == b"confidential evidence"
    with pytest.raises(ConfidentialityError):
        await service.read_evidence(evidence.id, company_id=company.id, actor_id=outsider.id)
    with pytest.raises(ConfidentialityError):
        await service.start_posh_inquiry(complaint.id, company_id=company.id, actor_id=user.id)
    await service.record_conciliation(
        complaint.id, company_id=company.id, actor_id=user.id, requested=True, status_value="REQUESTED",
    )
    with pytest.raises(ConfidentialityError):
        await service.record_conciliation(
            complaint.id, company_id=company.id, actor_id=user.id, requested=True,
            status_value="SETTLED", terms="Complainant cannot record the ICC outcome",
        )
    await service.record_conciliation(
        complaint.id, company_id=company.id, actor_id=icc_user.id, requested=True, status_value="FAILED",
    )
    await service.start_posh_inquiry(complaint.id, company_id=company.id, actor_id=icc_user.id)
    closed = await service.complete_posh_inquiry(
        complaint.id, company_id=company.id, actor_id=icc_user.id, recommendation="ICC recommendation recorded",
    )
    assert closed.status == "CLOSED"
    await service.record_training(
        company_id=company.id, audience="EMPLOYEE", training_title="POSH awareness",
        completed_at=datetime(2026, 2, 1, tzinfo=UTC), employee_id=employee.id,
    )
    annual = await service.generate_annual_return(company_id=company.id, return_year=2026, actor_id=user.id)
    assert annual.section_21["complaints_received"] == 1
    assert annual.section_21["complaints_disposed"] == 1
    assert annual.section_22["cases_pending"] == 0


@pytest.mark.asyncio
async def test_policy_targeting_acknowledgement_proof_and_reminders(db):
    company = await _company(db)
    entity = await _entity(db, company)
    branch = await _branch(db, company, entity)
    user = await _user(db, company)
    employee = await _employee(db, company, user, legal_entity_id=entity.id, branch_id=branch.id)
    other_user = await _user(db, company, "other")
    other = await _employee(db, company, other_user, department="Sales")
    service = PolicyGovernanceService(db)
    policy = await service.create_version(
        company_id=company.id, title="Field Work Policy", category="COMPLIANCE",
        raw_content="Employees must follow the published field-work controls.",
        version_number="2.0", acknowledgement_due_date=date.today() + timedelta(days=7),
        target_branch_ids=[str(branch.id)], target_departments=["Engineering"],
        target_roles=["employee"], target_employment_types=["FULL_TIME"],
    )
    policy, targeted = await service.publish(policy.id, company_id=company.id)
    assert targeted == 1
    assignments = (await db.execute(select(PolicyAcknowledgementAssignment))).scalars().all()
    assert [row.employee_id for row in assignments] == [employee.id]
    reminders = await service.trigger_reminders(company_id=company.id, now=datetime.now(UTC) + timedelta(days=8))
    assert len(reminders["reminders"]) == 1
    assert len(reminders["escalations"]) == 1
    from app.models.notification import UserNotification
    notifications = (await db.execute(select(UserNotification).where(
        UserNotification.company_id == company.id,
    ))).scalars().all()
    assert {notification.type for notification in notifications} >= {
        "policy.acknowledgement.reminder", "policy.acknowledgement.escalated",
    }
    acceptance = await service.acknowledge(
        policy.id, employee_id=employee.id, user_id=user.id, digital_signature="Real Employee",
        ip_address="203.0.113.10", user_agent="Batch5 PWA Test", request_id="ack-request-1",
    )
    proof = service.acknowledgement_proof(acceptance)
    assert proof["verified"] is True
    assert proof["ip_address"] == "203.0.113.10"
    assert proof["user_agent"] == "Batch5 PWA Test"
    assert len(proof["signature_hash"]) == 64
    assert assignments[0].status == "ACKNOWLEDGED"
    with pytest.raises(PermissionError):
        await service.acknowledge(
            policy.id, employee_id=other.id, user_id=other_user.id, digital_signature="Other User",
            ip_address=None, user_agent=None,
        )


@pytest.mark.asyncio
async def test_statutory_registers_and_live_filing_calendar(db):
    company = await _company(db)
    employee = await _employee(db, company)
    run = await _run(db, company, month=1, year=2026)
    await _payslip(db, company, run, employee, bonus=Decimal("500"), other_deductions=Decimal("25"))
    db.add(PayrollRunEmployee(
        id=uuid.uuid4(), run_id=run.id, employee_id=employee.id, company_id=company.id,
        deductions_breakup={"PF": 1800, "FINE": 25},
    ))
    period = PayrollPeriod(
        id=uuid.uuid4(), company_id=company.id, name="January 2026", start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31), processing_date=date(2026, 2, 1), pay_date=date(2026, 2, 5),
        period_month=1, period_year=2026,
    )
    db.add(period)
    await db.flush()
    db.add(VariableInput(
        id=uuid.uuid4(), employee_id=employee.id, company_id=company.id, period_id=period.id,
        type="FINE", amount_paise=2500, description="Documented disciplinary fine", status="APPROVED",
    ))
    db.add(Attendance(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id, date=date(2026, 1, 5),
        check_in_time=datetime(2026, 1, 5, 9, 0), check_out_time=datetime(2026, 1, 5, 18, 0),
        working_hours=9.0, status="Present", verified=True,
    ))
    await db.commit()
    service = ComplianceMonitorService(db)
    wage = await service.generate_statutory_register("FORM_B", company_id=company.id, year=2026, month=1)
    attendance = await service.generate_statutory_register("FORM_D", company_id=company.id, year=2026, month=1)
    deductions = await service.generate_statutory_register("FINES_DEDUCTIONS", company_id=company.id, year=2026, month=1)
    bonus = await service.generate_statutory_register("BONUS", company_id=company.id, year=2026, month=1)
    assert wage["rows"][0]["net_pay"] == 47500.0
    assert wage["csv_content"].startswith("employee_code,employee_name")
    assert attendance["rows"][0]["working_hours"] == 9.0
    assert deductions["rows"][0]["fine_amount"] == 25.0
    assert deductions["rows"][0]["deduction_breakup"]["PF"] == 1800
    assert bonus["rows"][0]["bonus_amount"] == 500.0
    summary = await StatutoryService.get_summary(db, period.id, component="ALL", company_id=company.id)
    assert summary["component"] == "ALL"
    assert len(summary["breakup"]) == 4
    assert summary["employee_contribution_paise"] == 180000

    rule = PayrollCompliance(
        id=uuid.uuid4(), company_id=company.id, compliance_name="Monthly PF", compliance_code="PF",
        filing_frequency="MONTHLY", due_day_of_month=15, is_enabled=True,
    )
    due = ComplianceDueDate(
        id=uuid.uuid4(), company_id=company.id, title="Overdue test filing", due_date=date.today() - timedelta(days=1),
        period="Test", period_month=date.today().month, period_year=date.today().year,
        filing_frequency="MONTHLY", status="PENDING",
    )
    db.add_all([rule, due])
    await db.commit()
    calendar_rows = await service.get_statutory_calendar(company_id=company.id, year=date.today().year, frequency="MONTHLY")
    overdue_row = next(row for row in calendar_rows if row["id"] == str(due.id))
    assert overdue_row["status"] == "OVERDUE"
    tracked = await service.track_statutory_filing(
        due.id, company_id=company.id, payment_date=due.due_date, filing_reference="ACK-001", utr_number="UTR001",
    )
    assert tracked.status == "FILED_ON_TIME"
    assert tracked.filing_reference == "ACK-001"


@pytest.mark.asyncio
async def test_bank_formats_and_utr_reconciliation_with_single_repayout(db):
    company = await _company(db)
    maker = await _user(db, company, "maker")
    checker = await _user(db, company, "checker", "admin")
    first_employee = await _employee(db, company)
    second_employee = await _employee(db, company)
    run = await _run(db, company)
    first_slip = await _payslip(db, company, run, first_employee)
    second_slip = await _payslip(db, company, run, second_employee)
    batch = PaymentBatch(
        id=uuid.uuid4(), company_id=company.id, run_id=run.id, batch_number=f"PB-{uuid.uuid4().hex[:10]}",
        source_account_id="9999999999", payment_mode="NEFT", status="DRAFT",
        created_by=maker.id, total_records=2, total_amount_paise=20000,
    )
    db.add(batch)
    await db.flush()
    first = PaymentBatchItem(
        id=uuid.uuid4(), batch_id=batch.id, employee_id=first_employee.id, company_id=company.id,
        amount_paise=10000, account_number="1111111111", ifsc_code="ICIC0000001",
        account_holder_name="First Employee", transaction_ref="TXN-1",
    )
    second = PaymentBatchItem(
        id=uuid.uuid4(), batch_id=batch.id, employee_id=second_employee.id, company_id=company.id,
        amount_paise=10000, account_number="2222222222", ifsc_code="HDFC0000002",
        account_holder_name="Second Employee", transaction_ref="TXN-2",
    )
    db.add_all([first, second])
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await PaymentBatchService.generate_bank_file(db, batch.id, "HDFC_ENET_CSV")
    assert exc.value.status_code == 409
    batch.status = "APPROVED"
    batch.approved_by = checker.id
    batch.approved_at = datetime.now()
    await db.commit()
    generated = {}
    for bank_format in ("ICICI_CORPORATE", "HDFC_ENET_CSV", "SBI_CMP_TXT", "GENERIC_NEFT_RTGS_CSV"):
        generated[bank_format] = await PaymentBatchService.generate_bank_file(db, batch.id, bank_format)
    assert generated["SBI_CMP_TXT"].file_name.endswith(".txt")
    assert "|" in generated["SBI_CMP_TXT"].file_content
    assert generated["ICICI_CORPORATE"].file_format == "ICICI_CORPORATE"

    with pytest.raises(HTTPException):
        await PaymentBatchService.reconcile_bank_feed(
            db, batch.id, [{"item_id": str(first.id), "status": "PAID"}], company_id=company.id,
        )
    rows = [
        {"item_id": str(first.id), "status": "SUCCESS", "utr_number": "UTR-PAID-1"},
        {"item_id": str(second.id), "status": "FAILED", "reason": "Account closed"},
    ]
    result = await PaymentBatchService.reconcile_bank_feed(
        db, batch.id, rows, company_id=company.id, user_id=checker.id, user_role="admin",
    )
    assert result["paid_count"] == 1 and result["failed_count"] == 1
    assert first.status == "PAID" and first.utr_number == "UTR-PAID-1"
    assert second.status == "FAILED" and second.repayout_batch_id is not None
    assert first_slip.payment_status == "PAID" and first_slip.payment_reference == "UTR-PAID-1"
    assert second_slip.payment_status == "FAILED"
    replay = await PaymentBatchService.reconcile_bank_feed(
        db, batch.id, rows, company_id=company.id, user_id=checker.id,
    )
    assert replay["repayout_batch_id"] == result["repayout_batch_id"]
    retry_count = (await db.execute(select(func.count(PaymentBatch.id)).where(PaymentBatch.retry_of_batch_id == batch.id))).scalar()
    assert retry_count == 1
    with pytest.raises(HTTPException):
        await PaymentBatchService.reconcile_bank_feed(
            db, batch.id, [{"item_id": str(first.id), "status": "FAILED"}], company_id=company.id,
        )


@pytest.mark.asyncio
async def test_multi_entity_scoping_state_calendar_and_due_transfer(db):
    company = await _company(db)
    user = await _user(db, company)
    entity_a = await _entity(db, company, "ENTITY-A", "MH")
    entity_b = await _entity(db, company, "ENTITY-B", "KA")
    branch_a = await _branch(db, company, entity_a, "MUMBAI", "MH")
    branch_b = await _branch(db, company, entity_b, "BENGALURU", "KA")
    employee_a = await _employee(db, company, legal_entity_id=entity_a.id, branch_id=branch_a.id)
    await _employee(db, company, legal_entity_id=entity_b.id, branch_id=branch_b.id)
    run = await _run(db, company, entity_id=entity_a.id)
    validation = await PayrollRunService.validate_run(db, run.id)
    assert validation["total_employees"] == 1
    state = await PayrollRunService.resolve_employee_statutory_state(db, employee_a)
    assert state["state_code"] == "MH" and state["state_source"] == "BRANCH"

    start = date(2026, 2, 1)
    end = date(2026, 2, calendar.monthrange(2026, 2)[1])
    calendar_row, period = await PayrollRunService.upsert_entity_payroll_calendar(
        db, legal_entity_id=entity_a.id, company_id=company.id, period_month=2, period_year=2026,
        start_date=start, end_date=end, processing_date=end, pay_date=date(2026, 3, 5),
        attendance_cutoff_date=end,
    )
    assert period.legal_entity_id == entity_a.id
    assert calendar_row.payroll_period_id == period.id
    same_calendar, _ = await PayrollRunService.upsert_entity_payroll_calendar(
        db, legal_entity_id=entity_a.id, company_id=company.id, period_month=2, period_year=2026,
        start_date=start, end_date=end, processing_date=end, pay_date=date(2026, 3, 6),
    )
    assert same_calendar.id == calendar_row.id
    assert (await db.execute(select(func.count(EntityPayrollCalendar.id)))).scalar() == 1

    effective = date.today() + timedelta(days=1)
    transfer = await PayrollRunService.transfer_employee(
        db, employee_id=employee_a.id, to_legal_entity_id=entity_b.id, to_branch_id=branch_b.id,
        effective_date=effective, reason="Entity restructuring", requested_by=user.id, company_id=company.id,
    )
    assert transfer.status == "SCHEDULED" and employee_a.legal_entity_id == entity_a.id
    assert await PayrollRunService.process_due_entity_transfers(db, company_id=company.id, as_of=date.today()) == 0
    assert await PayrollRunService.process_due_entity_transfers(db, company_id=company.id, as_of=effective) == 1
    assert employee_a.legal_entity_id == entity_b.id and employee_a.branch_id == branch_b.id


def test_batch5_migration_and_router_registration():
    from pathlib import Path
    migration = Path("alembic/versions/909a_batch5_employee_experience_compliance.py").read_text()
    assert 'down_revision = "908a_batch4_onboarding_fnf"' in migration
    for table in ("grievance_cases", "posh_complaints", "mobile_idempotency_records", "entity_payroll_calendars"):
        assert f'"{table}"' in migration
    from app.api.v2.router import v2_router
    paths = set()

    def collect_routes(router, prefix=""):
        for route in router.routes:
            if hasattr(route, "path"):
                paths.add(prefix + route.path)
            nested = getattr(route, "original_router", None)
            if nested is not None:  # FastAPI >= 0.16x lazy included router
                context = getattr(route, "include_context", None)
                collect_routes(nested, prefix + (getattr(context, "prefix", "") or ""))

    collect_routes(v2_router)
    assert "/api/v2/whatsapp/webhook" in paths
    assert "/api/v2/pwa/push-subscriptions" in paths
    assert "/api/v2/grievances" in paths
    assert "/api/v2/posh/complaints" in paths
    assert "/api/v2/payroll/statutory/registers/{register_type}" in paths
