"""Batch 6 focused service tests (SQLite; deterministic external-provider doubles)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("ENVIRONMENT", "local")

from app.db.base import Base
import app.models  # noqa: F401 - register production metadata
from app.models.accounting import ExpensePosting
from app.models.bgv import BGVCase
from app.models.company import Company
from app.models.employee import Employee
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_models import PayrollPeriod
from app.models.recruitment import Application, Candidate, Job
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.services.bgv_service import BGVService, make_consent_token, parse_consent_token
from app.services.compensation_service import CompensationBandService
from app.services.engagement_service import EngagementService
from app.services.internal_job_service import InternalJobService
from app.services.lms_service import LMSService
from app.services.payroll.accounting_service import EnterpriseAccountingService
from app.services.performance_service import PerformanceEnterpriseService
from app.services.recruitment_service import RecruitmentIntegrationService
from app.services.scim_service import SCIMService
from app.services.sso_service import SSOService
from app.services.succession_service import SuccessionService
from app.services.webhook_dispatcher_service import WebhookDispatcherService


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kwargs):
    return "JSON"


TEST_TABLES = [
    "companies", "users", "employees", "branches", "departments", "legal_entities", "shifts",
    "salary_structures", "recruitment_vendors", "candidates", "jobs", "applications",
    "payroll_periods", "payroll_runs", "payslips", "refresh_tokens",
    "bgv_vendors", "bgv_cases", "bgv_checks", "bgv_webhook_events",
    "succession_critical_roles", "succession_slates", "succession_development_actions",
    "compensation_bands", "employee_compensation_bands", "compensation_market_benchmarks", "department_increment_budgets",
    "performance_cycles_v2", "performance_reviews_360", "performance_calibration_runs", "performance_promotion_approvals",
    "internal_job_openings", "internal_job_applications",
    "lms_courses", "lms_modules", "lms_enrollments", "lms_module_progress", "lms_certificates",
    "engagement_surveys", "engagement_questions", "engagement_responses", "engagement_answers",
    "engagement_manager_action_plans", "engagement_peer_recognitions", "engagement_reward_ledger",
    "gl_account_mappings", "expense_postings", "gl_reconciliation_reports",
    "job_board_integrations", "job_board_syncs", "candidate_sources",
    "tenant_api_keys", "webhook_subscriptions", "webhook_deliveries", "webhook_delivery_attempts",
    "identity_providers", "external_identities", "sso_assertions", "scim_tokens", "scim_groups", "scim_group_members",
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [Base.metadata.tables[name] for name in TEST_TABLES]
    import re
    from sqlalchemy import text
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


async def _company(db: AsyncSession, name="Batch 6 Test Pvt Ltd") -> Company:
    company = Company(id=uuid.uuid4(), name=name)
    db.add(company)
    await db.flush()
    return company


async def _user(db: AsyncSession, company: Company, prefix="employee", role="employee") -> User:
    unique = uuid.uuid4().hex[:12]
    user = User(
        id=uuid.uuid4(), company_id=company.id, name=f"{prefix.title()} User",
        email=f"{prefix}-{unique}@example.com", phone=str(uuid.uuid4().int)[:10],
        password_hash="test-only-hash", role=role, is_active=True, is_verified=True,
        account_status="ACTIVE",
    )
    db.add(user)
    await db.flush()
    return user


async def _employee(
    db: AsyncSession, company: Company, user: User | None = None, *,
    department="Engineering", designation="Engineer", gender="MALE",
    joining_date=date(2020, 1, 1), role="employee", reporting_manager_id=None,
) -> Employee:
    unique = uuid.uuid4().hex[:10]
    employee = Employee(
        id=uuid.uuid4(), company_id=company.id, user_id=user.id if user else None,
        employee_id=f"EMP-{unique}", first_name="Batch", last_name="Employee",
        personal_email=f"employee-{unique}@example.com", phone="9876543210",
        department=department, designation=designation, joining_date=joining_date,
        employment_type="FULL_TIME", employment_status="CONFIRMED", status="ACTIVE",
        role=role, gender=gender, reporting_manager_id=reporting_manager_id,
        pan_number="ABCDE1234F",
    )
    db.add(employee)
    await db.flush()
    return employee


async def _job(db: AsyncSession, company: Company, creator: User | None = None) -> Job:
    unique = uuid.uuid4().hex[:10]
    job = Job(
        id=uuid.uuid4(), company_id=company.id, title="Platform Engineer", slug=f"platform-{unique}",
        department="Engineering", designation="Engineer", location="Jaipur", vacancies=1,
        job_description="Build reliable enterprise systems.", status="PUBLISHED",
        created_by=creator.id if creator else None,
    )
    db.add(job)
    await db.flush()
    return job


async def _application(db: AsyncSession, company: Company) -> tuple[Candidate, Application, Job]:
    job = await _job(db, company)
    unique = uuid.uuid4().hex[:10]
    candidate = Candidate(
        id=uuid.uuid4(), first_name="Candidate", last_name="Batch",
        email=f"candidate-{unique}@example.com", phone="9999999999", location="Jaipur",
        years_experience=Decimal("3"), source="DIRECT",
    )
    db.add(candidate)
    await db.flush()
    application = Application(
        id=uuid.uuid4(), company_id=company.id, job_id=job.id, candidate_id=candidate.id,
        first_name=candidate.first_name, last_name=candidate.last_name, email=candidate.email,
        phone=candidate.phone, country="India", state="Rajasthan", city="Jaipur",
        experience_years=Decimal("3"), declaration_checked=True, status="APPLIED",
    )
    db.add(application)
    await db.flush()
    return candidate, application, job


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_bgv_consent_signed_webhooks_discrepancy_and_tenant_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    admin = await _user(db, company, "bgv-admin", "hr_admin")
    _, application, _ = await _application(db, company)

    class Adapter:
        async def submit(self, vendor, case, checks):
            return {"reference": "BGV-EXT-001", "checks": {item.check_type: f"REF-{item.check_type}" for item in checks}}

    service = BGVService(db, adapter=Adapter())
    vendor = await service.create_vendor(
        company_id=company.id, name="Verifier", api_base_url="https://vendor.invalid", webhook_secret="bgv-secret-123456",
    )
    case = await service.create_case(
        company_id=company.id, vendor_id=vendor.id, actor_id=admin.id, application_id=application.id,
    )
    token = make_consent_token(case)
    assert parse_consent_token(token) == (case.id, company.id)
    with pytest.raises(ValueError):
        await service.submit_case(case.id, company_id=company.id)
    await service.capture_consent(
        case.id, company_id=company.id, accepted=True,
        consent_text="I explicitly consent to identity, criminal, education and employment verification.",
        ip_address="203.0.113.4", user_agent="candidate-browser",
    )
    case = await service.submit_case(case.id, company_id=company.id)
    assert case.status == "IN_PROGRESS" and len(case.checks) == 4

    for index, check in enumerate(case.checks):
        payload = {
            "event_id": f"event-{index}", "case_reference": "BGV-EXT-001",
            "check_type": check.check_type,
            "status": "DISCREPANCY" if check.check_type == "IDENTITY" else "CLEAR",
            "discrepancy_details": "Identity document mismatch" if check.check_type == "IDENTITY" else None,
        }
        raw = json.dumps(payload, sort_keys=True).encode()
        result = await service.handle_webhook(
            company_id=company.id, vendor_id=vendor.id, raw_body=raw, signature=_signature("bgv-secret-123456", raw),
        )
        assert result["duplicate"] is False
        if index == 0:
            replay = await service.handle_webhook(
                company_id=company.id, vendor_id=vendor.id, raw_body=raw, signature=_signature("bgv-secret-123456", raw),
            )
            assert replay["duplicate"] is True
    discrepancy = next(item for item in case.checks if item.discrepancy_flag)
    resolved = await service.resolve_discrepancy(
        discrepancy.id, company_id=company.id, actor_id=admin.id, resolution="RESOLVED", notes="Candidate supplied corrected evidence.",
    )
    assert resolved.resolution_status == "RESOLVED"
    assert (await db.get(BGVCase, case.id)).status == "COMPLETED_WITH_DISCREPANCY"
    with pytest.raises(PermissionError):
        await service.handle_webhook(company_id=company.id, vendor_id=vendor.id, raw_body=b"{}", signature="sha256=bad")
    with pytest.raises(LookupError):
        await service.resolve_discrepancy(discrepancy.id, company_id=other.id, actor_id=admin.id, resolution="RESOLVED", notes="Cross tenant attempt")


@pytest.mark.asyncio
async def test_succession_readiness_development_and_leadership_risk_map(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    incumbent = await _employee(db, company, designation="VP Engineering")
    successor = await _employee(db, company)
    service = SuccessionService(db)
    role = await service.create_critical_role(
        company_id=company.id, title="VP Engineering", department="Engineering",
        incumbent_employee_id=incumbent.id, vacancy_risk_score=85, business_impact_score=95,
    )
    slate = await service.add_successor(
        role.id, company_id=company.id, employee_id=successor.id,
        performance_score=90, potential_score=80, skill_coverage_score=70,
    )
    # 90*.4 + 80*.3 + 70*.3 = 81.
    assert float(slate.readiness_score) == 81 and slate.readiness_category == "READY_NOW"
    action = await service.add_development_action(
        slate.id, company_id=company.id, title="Executive finance rotation",
        owner_employee_id=successor.id, due_date=date.today() + timedelta(days=90),
    )
    action = await service.update_development_action(
        action.id, company_id=company.id, progress_percentage=100, evidence_reference="rotation-signoff",
    )
    assert action.status == "COMPLETED"
    risk_map = await service.leadership_risk_map(company_id=company.id)
    assert risk_map[0]["ready_now_count"] == 1 and risk_map[0]["coverage_risk"] == "MEDIUM"
    with pytest.raises(LookupError):
        await service.add_successor(role.id, company_id=other.id, employee_id=successor.id, performance_score=1, potential_score=1, skill_coverage_score=1)


@pytest.mark.asyncio
async def test_compensation_compa_ratio_market_budget_and_pay_equity(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    employees = [await _employee(db, company, gender="MALE" if i < 2 else "FEMALE") for i in range(4)]
    service = CompensationBandService(db)
    band = await service.create_band(
        company_id=company.id, band_code="ENG-L2", grade="L2", name="Engineer L2",
        min_paise=80000000, mid_paise=100000000, max_paise=120000000, effective_date=date(2026, 1, 1),
    )
    for index, employee in enumerate(employees):
        await service.assign_employee_band(
            company_id=company.id, employee_id=employee.id, band_id=band.id,
            annual_salary_paise=100000000 + index * 1000000, effective_date=date(2026, 1, 1),
        )
    metrics = await service.compa_ratio(company_id=company.id, employee_id=employees[0].id)
    assert metrics["compa_ratio"] == 1.0 and metrics["band_position"] == "WITHIN_BAND"
    await service.register_market_benchmark(
        company_id=company.id, grade="L2", designation="Engineer", region="IN",
        min_paise=90000000, median_paise=120000000, max_paise=130000000,
        source="Deterministic test benchmark", effective_date=date(2026, 1, 1),
    )
    market = await service.market_comparison(company_id=company.id, employee_id=employees[0].id)
    assert market["benchmark_found"] is True and market["market_position"] == "BELOW_MARKET"
    budget = await service.model_department_increment(
        company_id=company.id, department="Engineering", fiscal_year="2026-2027",
        budget_paise=20000000, recommendations={employees[0].id: 10},
    )
    assert budget.modeled_increment_paise == 10000000
    equity = await service.pay_equity_report(company_id=company.id)
    assert equity["methodology"] == "UNADJUSTED_AVERAGE_PAY_GAP" and len(equity["grades"]) == 1
    assert equity["grades"][0]["male"]["sample_count"] == 2 and not equity["grades"][0]["female"]["suppressed"]
    with pytest.raises(LookupError):
        await service.assign_employee_band(
            company_id=other.id, employee_id=employees[0].id, band_id=band.id,
            annual_salary_paise=1, effective_date=date.today(),
        )


@pytest.mark.asyncio
async def test_performance_360_calibration_promotion_and_tenant_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    manager = await _user(db, company, "manager", "manager")
    hr = await _user(db, company, "hr", "hr_admin")
    people = []
    for _ in range(2):
        user = await _user(db, company)
        people.append((user, await _employee(db, company, user)))
    bands = CompensationBandService(db)
    current_band = await bands.create_band(
        company_id=company.id, band_code="L2", grade="L2", name="Level 2",
        min_paise=80000000, mid_paise=100000000, max_paise=120000000, effective_date=date(2026, 1, 1),
    )
    target_band = await bands.create_band(
        company_id=company.id, band_code="L3", grade="L3", name="Level 3",
        min_paise=120000000, mid_paise=150000000, max_paise=180000000, effective_date=date(2026, 1, 1),
    )
    for _, employee in people:
        await bands.assign_employee_band(
            company_id=company.id, employee_id=employee.id, band_id=current_band.id,
            annual_salary_paise=100000000, effective_date=date(2026, 1, 1),
        )
    service = PerformanceEnterpriseService(db)
    cycle = await service.create_cycle(
        company_id=company.id, name="FY 2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )
    for index, (user, employee) in enumerate(people):
        self_review = await service.add_review(company_id=company.id, cycle_id=cycle.id, employee_id=employee.id, reviewer_id=user.id, review_type="SELF")
        await service.submit_review(self_review.id, company_id=company.id, reviewer_id=user.id, rating=4.5 - index * 0.5)
        manager_review = await service.add_review(company_id=company.id, cycle_id=cycle.id, employee_id=employee.id, reviewer_id=manager.id, review_type="MANAGER")
        await service.submit_review(manager_review.id, company_id=company.id, reviewer_id=manager.id, rating=4.8 - index)
    run = await service.calibrate_cycle(cycle.id, company_id=company.id, actor_id=hr.id)
    assert sum(run.result_json["actual_distribution"].values()) == 2
    assert all(row["calibrated_rating"] in {3, 4} for row in run.result_json["employees"])
    promotion = await service.create_promotion_request(
        company_id=company.id, cycle_id=cycle.id, employee_id=people[0][1].id,
        target_band_id=target_band.id, requested_by=manager.id, justification="Sustained impact and readiness for the next band.",
    )
    promotion = await service.decide_promotion(promotion.id, company_id=company.id, actor_id=manager.id, stage="MANAGER", approved=True)
    promotion = await service.decide_promotion(promotion.id, company_id=company.id, actor_id=hr.id, stage="HR", approved=True)
    assert promotion.status == "APPROVED" and promotion.recommended_increment_percentage > 0
    with pytest.raises(LookupError):
        await service.calibrate_cycle(cycle.id, company_id=other.id, actor_id=hr.id)


@pytest.mark.asyncio
async def test_internal_job_eligibility_idempotency_manager_gate_and_tenant_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    manager_user = await _user(db, company, "ijp-manager", "manager")
    manager = await _employee(db, company, manager_user, designation="Engineering Manager", role="manager")
    employee_user = await _user(db, company, "ijp-employee")
    employee = await _employee(db, company, employee_user, reporting_manager_id=manager.id)
    outsider = await _user(db, company, "outsider", "manager")
    service = InternalJobService(db)
    opening = await service.create_opening(
        company_id=company.id, title="Senior Platform Engineer", department="Engineering",
        designation="Senior Engineer", description="Internal growth opportunity.",
        min_tenure_months=12, created_by=manager_user.id,
    )
    eligibility = await service.check_eligibility(opening.id, company_id=company.id, employee_id=employee.id)
    assert eligibility["eligible"] is True and eligibility["tenure_months"] >= 12
    application = await service.apply(opening.id, company_id=company.id, employee_id=employee.id, cover_note="Ready for a new challenge.")
    assert application.status == "PENDING_MANAGER"
    assert (await service.apply(opening.id, company_id=company.id, employee_id=employee.id)).id == application.id
    with pytest.raises(PermissionError):
        await service.manager_decision(application.id, company_id=company.id, actor_user_id=outsider.id, actor_role="manager", approved=True)
    decided = await service.manager_decision(
        application.id, company_id=company.id, actor_user_id=manager_user.id, actor_role="manager", approved=True, reason="Strong internal successor.",
    )
    assert decided.status == "MANAGER_APPROVED"
    restrictive = await service.create_opening(
        company_id=company.id, title="Executive role", department="Engineering",
        designation="Executive", description="Long-tenure requirement.", min_tenure_months=1200,
    )
    ineligible = await service.apply(restrictive.id, company_id=company.id, employee_id=employee.id)
    assert ineligible.status == "INELIGIBLE" and "MINIMUM_TENURE_NOT_MET" in ineligible.eligibility_json["reasons"]
    with pytest.raises(LookupError):
        await service.check_eligibility(opening.id, company_id=other.id, employee_id=employee.id)


@pytest.mark.asyncio
async def test_lms_targeted_assignment_completion_pdf_and_compliance(db):
    from app.models.lms import LMSCertificate
    company, other = await _company(db), await _company(db, "Other Tenant")
    admin = await _user(db, company, "lms-admin", "hr_admin")
    employee = await _employee(db, company)
    await _employee(db, company, department="Sales")
    service = LMSService(db)
    course = await service.create_course(
        company_id=company.id, code="POSH-2026", title="Mandatory POSH Training",
        target_roles=["EMPLOYEE"], target_departments=["Engineering"],
        mandatory_for_compliance=True, validity_months=12,
    )
    module = await service.add_module(
        course.id, company_id=company.id, title="Policy essentials", content_type="TEXT",
        content_text="Complete mandatory compliance policy content.", sequence_number=1, duration_minutes=20,
    )
    with pytest.raises(ValueError):
        await service.publish_and_assign(course.id, company_id=company.id, actor_id=admin.id)
    enrollments = await service.publish_and_assign(
        course.id, company_id=company.id, actor_id=admin.id, due_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert len(enrollments) == 1 and enrollments[0].employee_id == employee.id and enrollments[0].is_mandatory
    completed = await service.complete_module(enrollments[0].id, module.id, company_id=company.id, employee_id=employee.id)
    assert completed.status == "COMPLETED" and completed.progress_percentage == 100
    certificate = (await db.execute(select(LMSCertificate).where(LMSCertificate.enrollment_id == completed.id))).scalar_one()
    pdf, filename = await service.certificate_pdf(certificate.id, company_id=company.id)
    assert pdf.startswith(b"%PDF") and filename.endswith(".pdf")
    compliance = await service.mandatory_compliance_status(company_id=company.id)
    assert compliance["assigned"] == 1 and compliance["completed"] == 1 and compliance["overdue"] == 0
    with pytest.raises(LookupError):
        await service.complete_module(completed.id, module.id, company_id=other.id, employee_id=employee.id)


@pytest.mark.asyncio
async def test_engagement_enps_k_anonymity_recurring_actions_and_rewards(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    manager = await _employee(db, company, designation="Engineering Manager", role="manager")
    employees = [await _employee(db, company), await _employee(db, company), await _employee(db, company, department="Sales")]
    service = EngagementService(db)
    now = datetime.now(UTC)
    survey = await service.create_survey(
        company_id=company.id, title="Weekly pulse", starts_at=now - timedelta(hours=1), ends_at=now + timedelta(days=1),
        frequency="WEEKLY", anonymous=True, min_group_size=2,
        questions=[
            {"question_text": "How likely are you to recommend us?", "question_type": "ENPS"},
            {"question_text": "What should improve?", "question_type": "TEXT"},
        ],
    )
    enps = next(q for q in survey.questions if q.question_type == "ENPS")
    text = next(q for q in survey.questions if q.question_type == "TEXT")
    for employee, score in zip(employees, [10, 0, 9]):
        response = await service.submit_response(
            survey.id, company_id=company.id, employee_id=employee.id,
            answers={enps.id: {"numeric_value": score}, text.id: {"text_value": "Deterministic anonymous feedback"}},
            submitted_at=now,
        )
        assert response.employee_id is None
    with pytest.raises(ValueError):
        await service.submit_response(
            survey.id, company_id=company.id, employee_id=employees[0].id,
            answers={enps.id: {"numeric_value": 8}, text.id: {"text_value": "Duplicate"}}, submitted_at=now,
        )
    results = await service.survey_results(survey.id, company_id=company.id)
    assert results["overall"]["enps"] == 33.33
    assert results["departments"]["Engineering"]["enps"] == 0.0
    assert results["departments"]["Sales"]["suppressed"] is True and results["departments"]["Sales"]["comments"] == []
    plan = await service.create_action_plan(
        company_id=company.id, manager_employee_id=manager.id, survey_id=survey.id,
        title="Act on pulse feedback", actions=[{"action": "Weekly listening session", "owner": "manager"}], due_date=date.today() + timedelta(days=14),
    )
    assert plan.status == "OPEN"
    recognition = await service.recognize_peer(
        company_id=company.id, sender_employee_id=employees[0].id, recipient_employee_id=employees[1].id,
        message="Excellent customer escalation handling.", points=50,
    )
    assert recognition.status == "APPROVED"
    await service.redeem_rewards(company_id=company.id, employee_id=employees[1].id, points=20, reference="REWARD-001")
    assert await service.reward_balance(company_id=company.id, employee_id=employees[1].id) == 30
    with pytest.raises(LookupError):
        await service.survey_results(survey.id, company_id=other.id)


@pytest.mark.asyncio
async def test_enterprise_accounting_balanced_exports_expenses_and_reconciliation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    employee = await _employee(db, company)
    period = PayrollPeriod(
        id=uuid.uuid4(), company_id=company.id, name="January 2026", start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31), pay_date=date(2026, 1, 31), period_month=1, period_year=2026, status="CLOSED",
    )
    db.add(period)
    await db.flush()
    run = PayrollRun(
        id=uuid.uuid4(), company_id=company.id, period_id=period.id, period_month=1, period_year=2026,
        run_number=f"PR-{uuid.uuid4().hex[:10]}", status="APPROVED",
    )
    db.add(run)
    await db.flush()
    db.add(Payslip(
        id=uuid.uuid4(), company_id=company.id, payroll_run_id=run.id, employee_id=employee.id,
        payslip_number=f"PAY-{uuid.uuid4().hex[:12]}", period_month=1, period_year=2026,
        total_days_in_month=31, paid_days=Decimal("31"), basic=Decimal("30000"), hra=Decimal("12000"),
        gross_earnings=Decimal("50000"), employee_pf=Decimal("1800"), employer_pf=Decimal("1800"),
        total_deductions=Decimal("2500"), net_pay=Decimal("47500"),
    ))
    await db.commit()
    service = EnterpriseAccountingService(db)
    journal = await service.build_journal(company_id=company.id, period_id=period.id)
    assert journal["is_balanced"] is True and journal["total_debit_paise"] == journal["total_credit_paise"] == 5180000
    for export_format, marker in [("TALLY_XML", "<ENVELOPE>"), ("TALLY_CSV", "Account Code"), ("ZOHO_JSON", "journal_entries"), ("ZOHO_CSV", "Account Code")]:
        exported = await service.export_journal(company_id=company.id, period_id=period.id, export_format=export_format)
        assert marker in exported["content"]
    expense = await service.post_expense(
        company_id=company.id, employee_id=employee.id, expense_date=date(2026, 1, 15), category="TRAVEL",
        amount_paise=125050, description="Client visit taxi", idempotency_key="EXPENSE-IDEMPOTENT-001",
    )
    replay = await service.post_expense(
        company_id=company.id, employee_id=employee.id, expense_date=date(2026, 1, 15), category="TRAVEL",
        amount_paise=125050, description="Client visit taxi", idempotency_key="EXPENSE-IDEMPOTENT-001",
    )
    assert replay.id == expense.id and (await db.execute(select(ExpensePosting))).scalars().all()[0].amount_paise == 125050
    reconciliation = await service.reconcile_gl(
        company_id=company.id, period_id=period.id, provider="GENERIC", external_entries=journal["entries"],
    )
    assert reconciliation.status == "MATCHED" and reconciliation.difference_paise == 0
    with pytest.raises(LookupError):
        await service.build_journal(company_id=other.id, period_id=period.id)


@pytest.mark.asyncio
async def test_recruitment_provider_sync_signed_ingestion_utm_and_tenant_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    creator = await _user(db, company, "recruiter", "hr_admin")
    job = await _job(db, company, creator)

    class Adapter:
        async def sync_job(self, integration, job):
            return {"id": "NAUKRI-JOB-001", "status": "published"}

    service = RecruitmentIntegrationService(db, adapters={"NAUKRI": Adapter()})
    await service.configure_integration(
        company_id=company.id, provider="NAUKRI", api_base_url="https://naukri.invalid",
        api_token="provider-token", webhook_secret="recruitment-secret-123",
    )
    sync = await service.sync_job(job.id, company_id=company.id, provider="NAUKRI")
    assert sync.status == "SYNCED" and sync.external_job_id == "NAUKRI-JOB-001"
    payload = {
        "candidate_id": "NAUKRI-CAND-001", "job_id": str(job.id), "email": "board-candidate@example.com",
        "first_name": "Board", "last_name": "Candidate", "utm": {"utm_source": "naukri", "utm_medium": "paid", "utm_campaign": "engineering-q4"},
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    result = await service.ingest_candidate_webhook(
        company_id=company.id, provider="NAUKRI", raw_body=raw, signature=_signature("recruitment-secret-123", raw),
    )
    assert result["duplicate"] is False
    replay = await service.ingest_candidate_webhook(
        company_id=company.id, provider="NAUKRI", raw_body=raw, signature=_signature("recruitment-secret-123", raw),
    )
    assert replay["duplicate"] is True and replay["application_id"] == result["application_id"]
    analytics = await service.source_analytics(company_id=company.id)
    assert analytics["total_candidates"] == 1 and analytics["sources"][0]["utm_campaign"] == "engineering-q4"
    with pytest.raises(PermissionError):
        await service.ingest_candidate_webhook(company_id=company.id, provider="NAUKRI", raw_body=raw, signature="sha256=bad")
    with pytest.raises(LookupError):
        await service.sync_job(job.id, company_id=other.id, provider="NAUKRI")


@pytest.mark.asyncio
async def test_developer_keys_signed_retries_audit_and_tenant_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    admin = await _user(db, company, "developer-admin", "hr_admin")
    calls = []

    async def transport(url, body, headers):
        calls.append((url, body, headers))
        return (500, "receiver unavailable") if len(calls) == 1 else (200, "accepted")

    service = WebhookDispatcherService(db, transport=transport)
    key, raw_key = await service.create_api_key(
        company_id=company.id, name="Employee feed", scopes=["employee:read"], created_by=admin.id,
    )
    assert raw_key != key.key_hash and (await service.authenticate_api_key(raw_key, "employee:read")).id == key.id
    with pytest.raises(PermissionError):
        await service.authenticate_api_key(raw_key, "payroll:write")
    await service.revoke_api_key(key.id, company_id=company.id)
    with pytest.raises(PermissionError):
        await service.authenticate_api_key(raw_key, "employee:read")
    subscription, secret = await service.create_subscription(
        company_id=company.id, target_url="https://example.com/webhooks/ofc360", events=["employee.created"], created_by=admin.id,
    )
    deliveries = await service.publish(company_id=company.id, event_type="employee.created", data={"employee_id": "E-1"}, event_id="EVENT-1")
    assert len(deliveries) == 1 and not await service.publish(company_id=other.id, event_type="employee.created", data={}, event_id="EVENT-OTHER")
    delivery = await service.deliver(deliveries[0].id, company_id=company.id)
    assert delivery.status == "RETRY" and delivery.attempt_count == 1
    signature = calls[0][2]["X-OFC360-Signature"]
    timestamp = int(signature.split(",", 1)[0].split("=", 1)[1])
    assert signature == service.signature(secret, calls[0][1], timestamp)
    delivery = await service.retry_delivery(delivery.id, company_id=company.id)
    assert delivery.status == "DELIVERED" and delivery.attempt_count == 2 and len(calls) == 2
    assert len(await service.list_subscriptions(company_id=company.id)) == 1
    with pytest.raises(LookupError):
        await service.retry_delivery(delivery.id, company_id=other.id)


@pytest.mark.asyncio
async def test_scim_user_group_provisioning_immediate_deprovisioning_and_tenant_isolation(db, monkeypatch):
    company, other = await _company(db), await _company(db, "Other Tenant")
    admin = await _user(db, company, "scim-admin", "hr_admin")
    other_admin = await _user(db, other, "other-scim-admin", "hr_admin")
    service = SCIMService(db)
    token, raw_token = await service.create_token(
        company_id=company.id, name="Entra provisioning", scopes=["scim:users", "scim:groups"], created_by=admin.id,
    )
    assert raw_token != token.token_hash and (await service.authenticate(raw_token, "scim:users")).company_id == company.id
    user = await service.create_user(
        company_id=company.id, payload={"userName": "scim-user@example.com", "displayName": "SCIM User", "active": True, "externalId": "ENTRA-USER-1"},
    )
    assert user.is_active and user.company_id == company.id
    refresh = await AuthRepository(db).create_refresh_token(
        user_id=user.id, token_hash=hashlib.sha256(b"scim-refresh").hexdigest(), expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await db.commit()
    previous_version = user.token_version
    revoke_tokens = AsyncMock(return_value=True)
    invalidate_cache = AsyncMock()
    monkeypatch.setattr("app.services.scim_service.redis_client.revoke_user_tokens", revoke_tokens)
    monkeypatch.setattr("app.services.scim_service.invalidate_auth_active_cache", invalidate_cache)
    await service.deprovision_user(user.id, company_id=company.id)
    assert not user.is_active and user.account_status == "DEACTIVATED" and user.token_version > previous_version
    await db.refresh(refresh)
    assert refresh.revoked is True
    revoke_tokens.assert_awaited_once_with(user.id)
    invalidate_cache.assert_awaited_once_with(user.id, company.id)
    group = await service.create_group(
        company_id=company.id, payload={"displayName": "Engineering", "members": [{"value": str(user.id)}]},
    )
    assert group.members[0].user_id == user.id
    with pytest.raises(LookupError):
        await service.get_user(user.id, company_id=other.id)
    with pytest.raises(ValueError):
        await service.create_group(company_id=other.id, payload={"displayName": "Cross tenant", "members": [{"value": str(user.id)}]})
    other_token, other_raw = await service.create_token(company_id=other.id, name="Other", scopes=["scim:users"], created_by=other_admin.id)
    assert (await service.authenticate(other_raw, "scim:users")).company_id == other.id
    with pytest.raises(PermissionError):
        await service.authenticate(other_raw, "scim:groups")


def _rsa_test_material():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def b64uint(value):
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwks = {"keys": [{"kty": "RSA", "kid": "batch6-test", "use": "sig", "alg": "RS256", "n": b64uint(public_numbers.n), "e": b64uint(public_numbers.e)}]}
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    )
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Batch 6 Test IdP")])
    certificate = x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(
        private_key.public_key(),
    ).serial_number(x509.random_serial_number()).not_valid_before(
        datetime.now(UTC) - timedelta(days=1),
    ).not_valid_after(datetime.now(UTC) + timedelta(days=30)).sign(private_key, __import__("cryptography").hazmat.primitives.hashes.SHA256())
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
    return private_key, private_pem, certificate_pem, jwks


def _signed_saml_response(private_key, *, email: str, recipient: str, audience: str, now: datetime):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from lxml import etree
    assertion_ns = "urn:oasis:names:tc:SAML:2.0:assertion"
    protocol_ns = "urn:oasis:names:tc:SAML:2.0:protocol"
    ds_ns = "http://www.w3.org/2000/09/xmldsig#"
    c14n = "http://www.w3.org/2001/10/xml-exc-c14n#"
    response = etree.Element(f"{{{protocol_ns}}}Response", nsmap={"saml2p": protocol_ns})
    assertion = etree.SubElement(response, f"{{{assertion_ns}}}Assertion", nsmap={"saml2": assertion_ns, "ds": ds_ns})
    assertion_id = "_" + uuid.uuid4().hex
    assertion.set("ID", assertion_id)
    assertion.set("Version", "2.0")
    assertion.set("IssueInstant", now.isoformat().replace("+00:00", "Z"))
    etree.SubElement(assertion, f"{{{assertion_ns}}}Issuer").text = "https://idp.example.com"
    subject = etree.SubElement(assertion, f"{{{assertion_ns}}}Subject")
    etree.SubElement(subject, f"{{{assertion_ns}}}NameID").text = email
    confirmation = etree.SubElement(subject, f"{{{assertion_ns}}}SubjectConfirmation")
    confirmation_data = etree.SubElement(confirmation, f"{{{assertion_ns}}}SubjectConfirmationData")
    confirmation_data.set("Recipient", recipient)
    confirmation_data.set("NotOnOrAfter", (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    conditions = etree.SubElement(assertion, f"{{{assertion_ns}}}Conditions")
    conditions.set("NotBefore", (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"))
    conditions.set("NotOnOrAfter", (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    restriction = etree.SubElement(conditions, f"{{{assertion_ns}}}AudienceRestriction")
    etree.SubElement(restriction, f"{{{assertion_ns}}}Audience").text = audience
    attributes = etree.SubElement(assertion, f"{{{assertion_ns}}}AttributeStatement")
    for name, value in [("email", email), ("first_name", "SAML"), ("last_name", "User")]:
        attribute = etree.SubElement(attributes, f"{{{assertion_ns}}}Attribute")
        attribute.set("Name", name)
        etree.SubElement(attribute, f"{{{assertion_ns}}}AttributeValue").text = value
    digest = base64.b64encode(hashlib.sha256(etree.tostring(assertion, method="c14n", exclusive=True, with_comments=False)).digest()).decode()
    signature = etree.Element(f"{{{ds_ns}}}Signature")
    signed_info = etree.SubElement(signature, f"{{{ds_ns}}}SignedInfo")
    etree.SubElement(signed_info, f"{{{ds_ns}}}CanonicalizationMethod").set("Algorithm", c14n)
    etree.SubElement(signed_info, f"{{{ds_ns}}}SignatureMethod").set("Algorithm", "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")
    reference = etree.SubElement(signed_info, f"{{{ds_ns}}}Reference")
    reference.set("URI", f"#{assertion_id}")
    transforms = etree.SubElement(reference, f"{{{ds_ns}}}Transforms")
    etree.SubElement(transforms, f"{{{ds_ns}}}Transform").set("Algorithm", "http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    etree.SubElement(transforms, f"{{{ds_ns}}}Transform").set("Algorithm", c14n)
    etree.SubElement(reference, f"{{{ds_ns}}}DigestMethod").set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    etree.SubElement(reference, f"{{{ds_ns}}}DigestValue").text = digest
    signature_value = etree.SubElement(signature, f"{{{ds_ns}}}SignatureValue")
    assertion.insert(1, signature)
    signed = private_key.sign(etree.tostring(signed_info, method="c14n", exclusive=True, with_comments=False), padding.PKCS1v15(), hashes.SHA256())
    signature_value.text = base64.b64encode(signed).decode()
    raw = etree.tostring(response, encoding="utf-8", xml_declaration=True)
    return base64.b64encode(raw).decode(), raw


@pytest.mark.asyncio
async def test_oidc_google_workspace_rs256_nonce_domain_and_tenant_isolation(db):
    from jose import jwt
    company, other = await _company(db), await _company(db, "Other Tenant")
    _, private_pem, _, jwks = _rsa_test_material()
    service = SSOService(db)
    issuer = "https://accounts.example.com"
    config = dict(
        allowed_domains=["example.com"], client_id="workspace-client", client_secret="oidc-secret",
        issuer=issuer, authorization_endpoint="https://idp.example.com/auth",
        token_endpoint="https://idp.example.com/token", jwks_uri="https://idp.example.com/jwks",
    )
    await service.configure_provider(company_id=company.id, provider_type="GOOGLE_OIDC", **config)
    await service.configure_provider(company_id=company.id, provider_type="MICROSOFT_OIDC", **config)
    microsoft_url = await service.authorization_url(
        company_id=company.id, provider_type="MICROSOFT_OIDC", redirect_uri="https://sp.example.com/callback",
        state="signed-state", nonce="expected-nonce",
    )
    assert "client_id=workspace-client" in microsoft_url and "nonce=expected-nonce" in microsoft_url
    now = datetime.now(UTC)
    claims = {
        "sub": "GOOGLE-SUBJECT-1", "iss": issuer, "aud": "workspace-client",
        "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "expected-nonce", "email": "oidc-user@example.com", "email_verified": True,
        "given_name": "OIDC", "family_name": "User", "hd": "example.com",
    }
    token = jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": "batch6-test"})
    user = await service.authenticate_oidc(
        company_id=company.id, provider_type="GOOGLE_OIDC", code="deterministic-code",
        redirect_uri="https://sp.example.com/callback", expected_nonce="expected-nonce", id_token=token, jwks=jwks,
    )
    assert user.email == "oidc-user@example.com" and user.company_id == company.id and user.is_active
    with pytest.raises(PermissionError):
        await service.authenticate_oidc(
            company_id=company.id, provider_type="GOOGLE_OIDC", code="code", redirect_uri="https://sp.example.com/callback",
            expected_nonce="wrong-nonce", id_token=token, jwks=jwks,
        )
    with pytest.raises(PermissionError):
        await service.authenticate_oidc(
            company_id=company.id, provider_type="GOOGLE_OIDC", code="code", redirect_uri="https://sp.example.com/callback",
            expected_nonce="expected-nonce", id_token=token + "tampered", jwks=jwks,
        )
    existing = await _user(db, other, "existing-oidc")
    existing.email = "existing-oidc@example.com"
    await db.commit()
    await service.configure_provider(company_id=other.id, provider_type="GOOGLE_OIDC", **config)
    other_claims = {**claims, "sub": "GOOGLE-SUBJECT-2", "email": existing.email}
    other_token = jwt.encode(other_claims, private_pem, algorithm="RS256", headers={"kid": "batch6-test"})
    with pytest.raises(PermissionError):
        await service.authenticate_oidc(
            company_id=company.id, provider_type="GOOGLE_OIDC", code="code", redirect_uri="https://sp.example.com/callback",
            expected_nonce="expected-nonce", id_token=other_token, jwks=jwks,
        )


@pytest.mark.asyncio
async def test_saml_signed_assertion_acs_replay_tamper_and_audience_validation(db):
    company = await _company(db)
    private_key, _, certificate_pem, _ = _rsa_test_material()
    service = SSOService(db)
    recipient, audience = "https://sp.example.com/api/v1/auth/saml/acs", "https://sp.example.com/saml"
    await service.configure_provider(
        company_id=company.id, provider_type="SAML", allowed_domains=["example.com"],
        x509_certificate=certificate_pem.decode(), sp_entity_id=audience,
        saml_sso_url="https://idp.example.com/sso",
    )
    now = datetime.now(UTC).replace(microsecond=0)
    encoded, raw = _signed_saml_response(
        private_key, email="saml-user@example.com", recipient=recipient, audience=audience, now=now,
    )
    user = await service.authenticate_saml(company_id=company.id, encoded_response=encoded, recipient_url=recipient, now=now)
    assert user.email == "saml-user@example.com" and user.company_id == company.id
    with pytest.raises(PermissionError, match="already been consumed"):
        await service.authenticate_saml(company_id=company.id, encoded_response=encoded, recipient_url=recipient, now=now)
    from lxml import etree
    root = etree.fromstring(raw)
    name_id = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    name_id.text = "attacker@example.com"
    tampered = base64.b64encode(etree.tostring(root)).decode()
    with pytest.raises(PermissionError):
        await service.authenticate_saml(company_id=company.id, encoded_response=tampered, recipient_url=recipient, now=now)
    wrong_audience, _ = _signed_saml_response(
        private_key, email="other-saml-user@example.com", recipient=recipient, audience="https://other-sp.example.com", now=now,
    )
    with pytest.raises(PermissionError):
        await service.authenticate_saml(company_id=company.id, encoded_response=wrong_audience, recipient_url=recipient, now=now)
