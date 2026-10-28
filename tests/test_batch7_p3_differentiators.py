"""Batch 7 focused tests: P3 differentiators (features 34 through 44)."""
from __future__ import annotations

import io
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pypdf import PdfReader
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ.setdefault("ENVIRONMENT", "local")

from app.db.base import Base
import app.models  # noqa: F401 - register production metadata
from app.models.ai_employee_support import SupportTicket
from app.models.company import Company
from app.models.compensation import CompensationBand, EmployeeCompensationBand
from app.models.digital_twin import OrgTwinSimulation
from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.employee_risk import EmployeeRiskAssessment
from app.models.employee_skill import EmployeeSkill
from app.models.engagement import EngagementAnswer, EngagementQuestion, EngagementResponse, EngagementSurvey
from app.models.grievance_posh import GrievanceCase
from app.models.marketplace import MarketplaceIntegration
from app.models.payroll import OvertimeEntry, PayrollRun, Payslip, SalaryStructure
from app.models.payroll_models import Compensation, PayrollPeriod, PayrollRunEmployee
from app.models.policy import CompanyPolicyChunk, CompanyPolicyDocument
from app.models.recruitment import Application, Candidate, Job
from app.models.user import User
from app.models.workforce_forecast import WorkforcePlan
from app.services.ai_copilot_service import AiCopilotService
from app.services.enterprise_intelligence_services import WorkforcePlanningService
from app.services.hr_differentiator_analytics import HRDifferentiatorAnalytics
from app.services.marketplace_service import CONNECTOR_CATALOG, MarketplaceService
from app.services.org_intelligence_services import OrgTwinSimulationService
from app.services.payroll.compensation_service import CompensationService as PayrollCompensationService
from app.services.payroll.global_payroll import (
    CountryStatutoryInput, SUPPORTED_CURRENCIES, convert_minor_units,
    get_country_statutory_calculator,
)
from app.services.payroll.payslip_service import PayslipService
from app.services.payroll.run_service import PayrollRunService
from app.services.whitelabel_service import WhiteLabelService


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kwargs):
    return "JSON"


TEST_TABLES = [
    "companies", "users", "legal_entities", "branches", "departments", "shifts", "employees",
    "salary_structures", "compensations", "compensation_bands", "employee_compensation_bands",
    "payroll_periods", "pay_cycles", "payroll_runs", "payroll_run_employees", "payslips", "payroll_audit_logs",
    "employee_bank_accounts", "payroll_attendance_inputs", "advance_loans", "advance_loan_installments",
    "variable_inputs", "arrear_ledgers", "statutory_compliance_configs", "employee_investment_declarations",
    "pay_components", "employee_ytd_salaries",
    "recruitment_vendors", "candidates", "jobs", "applications",
    "company_policy_documents", "company_policy_chunks", "grievance_cases",
    "posh_icc_committees", "posh_complaints",
    "engagement_surveys", "engagement_questions", "engagement_responses", "engagement_answers",
    "overtime_entries", "employee_leave_policies", "support_tickets",
    "employee_risk_assessments", "workforce_plans", "org_twin_simulations", "employee_skills",
    "marketplace_integrations", "integration_sync_logs",
]


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    tables = [Base.metadata.tables[name] for name in TEST_TABLES]
    import re
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


async def _company(db: AsyncSession, name="Batch 7 Pvt Ltd") -> Company:
    row = Company(id=uuid.uuid4(), name=name)
    db.add(row)
    await db.flush()
    return row


async def _user(db: AsyncSession, company: Company, prefix="admin") -> User:
    unique = uuid.uuid4().hex[:12]
    row = User(
        id=uuid.uuid4(), company_id=company.id, name="Batch 7 Admin",
        email=f"{prefix}-{unique}@example.com", phone=str(uuid.uuid4().int)[:10],
        password_hash="test-only-hash", role="hr_admin", is_active=True,
        is_verified=True, account_status="ACTIVE",
    )
    db.add(row)
    await db.flush()
    return row


async def _employee(
    db: AsyncSession, company: Company, *, department="Engineering", designation="Engineer",
    gender="MALE", joining_date=date(2022, 1, 1), status="ACTIVE", manager_id=None,
    date_of_birth=date(1990, 1, 1), last_promotion_date=None, employee_category=None,
    role_metadata=None, ctc=0, user_id=None,
) -> Employee:
    unique = uuid.uuid4().hex[:10]
    row = Employee(
        id=uuid.uuid4(), company_id=company.id, user_id=user_id,
        employee_id=f"B7-{unique}", first_name="Batch", last_name="Seven",
        personal_email=f"b7-{unique}@example.com", phone="9876543210",
        department=department, designation=designation, joining_date=joining_date,
        employment_type="FULL_TIME", employment_status="CONFIRMED", status=status,
        role="employee", gender=gender, reporting_manager_id=manager_id,
        date_of_birth=date_of_birth, last_promotion_date=last_promotion_date,
        employee_category=employee_category, role_metadata=role_metadata or {},
        pan_number="ABCDE1234F", ctc=ctc,
    )
    db.add(row)
    await db.flush()
    return row


async def _band(db: AsyncSession, company: Company, *, grade="L5") -> CompensationBand:
    row = CompensationBand(
        id=uuid.uuid4(), company_id=company.id, band_code=f"BAND-{uuid.uuid4().hex[:8]}",
        grade=grade, name="Engineering Band", department="Engineering",
        min_paise=8_000_000, mid_paise=10_000_000, max_paise=12_000_000,
        currency="INR", effective_date=date(2026, 1, 1), is_active=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _assignment(db, company, employee, band, annual=7_000_000):
    row = EmployeeCompensationBand(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id, band_id=band.id,
        annual_salary_paise=annual, effective_date=date(2026, 1, 1), is_current=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _job(db, company, *, department="Engineering", status="PUBLISHED", vacancies=2):
    row = Job(
        id=uuid.uuid4(), company_id=company.id, title="Platform Engineer",
        slug=f"platform-{uuid.uuid4().hex[:10]}", department=department, designation="Engineer",
        location="Jaipur", vacancies=vacancies, job_description="Build reliable systems.",
        status=status, min_salary=Decimal("100000"), max_salary=Decimal("200000"),
    )
    db.add(row)
    await db.flush()
    return row


async def _application(db, company, job, *, gender=None, consented=False, status="APPLIED"):
    unique = uuid.uuid4().hex[:10]
    candidate = Candidate(
        id=uuid.uuid4(), first_name="Candidate", last_name=unique,
        email=f"candidate-{unique}@example.com", phone="9999999999", location="Jaipur",
        years_experience=Decimal("3"), source="DIRECT",
    )
    db.add(candidate)
    await db.flush()
    row = Application(
        id=uuid.uuid4(), company_id=company.id, job_id=job.id, candidate_id=candidate.id,
        first_name=candidate.first_name, last_name=candidate.last_name, email=candidate.email,
        phone=candidate.phone, country="India", state="Rajasthan", city="Jaipur",
        experience_years=Decimal("3"), declaration_checked=True, status=status,
        voluntary_demographics={"gender": gender} if gender else None,
        diversity_consent_at=datetime.now(UTC) if consented else None,
    )
    db.add(row)
    await db.flush()
    return row


async def _period(db, company, *, month=1):
    row = PayrollPeriod(
        id=uuid.uuid4(), company_id=company.id, name=f"Period {month}", start_date=date(2026, month, 1),
        end_date=date(2026, month, 28), pay_date=date(2026, month, 28),
        processing_date=date(2026, month, 28), period_month=month, period_year=2026,
    )
    db.add(row)
    await db.flush()
    return row


def _copilot(db):
    return AiCopilotService(session=db, repo=SimpleNamespace(), ollama=SimpleNamespace())


@pytest.mark.asyncio
async def test_salary_negotiation_three_budgeted_scenarios_and_tenant_guard(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    band = await _band(db, company)
    result = await _copilot(db).salary_negotiation_copilot(
        company_id=company.id, band_id=band.id, candidate_name="Candidate A",
        candidate_match_score=0.8, hiring_budget_annual_paise=11_000_000,
        expected_ctc_annual_paise=10_500_000,
    )
    assert len(result["scenarios"]) == 3
    assert [row["scenario"] for row in result["scenarios"]] == ["CONSERVATIVE", "RECOMMENDED", "STRETCH"]
    for row in result["scenarios"]:
        assert row["ctc_annual_paise"] <= 11_000_000
        assert row["fixed_ctc_annual_paise"] + row["variable_pay_annual_paise"] + row["signing_bonus_paise"] == row["ctc_annual_paise"]
        assert row["negotiation_script"]["concession_guardrail"]
        assert row["compa_ratio"] == pytest.approx(row["ctc_annual_paise"] / 10_000_000, abs=0.0001)
    assert result["requires_compensation_approval"] is True
    constrained = await _copilot(db).salary_negotiation_copilot(
        company_id=company.id, band_id=band.id, candidate_name="Low Budget Candidate",
        candidate_match_score=0.8, hiring_budget_annual_paise=1_000_000,
    )
    assert constrained["budget_feasible_for_band"] is False
    assert all(row["band_position"] == "BELOW_BAND" for row in constrained["scenarios"])
    assert all(not row["issuable_without_band_exception"] for row in constrained["scenarios"])
    assert all("not issuable" in row["negotiation_script"]["opening"] for row in constrained["scenarios"])
    with pytest.raises(LookupError):
        await _copilot(db).salary_negotiation_copilot(
            company_id=other.id, band_id=band.id, candidate_name="Cross Tenant",
            candidate_match_score=0.8, hiring_budget_annual_paise=11_000_000,
        )


@pytest.mark.asyncio
async def test_disciplinary_assistant_grounded_notice_checklist_and_precedents(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    employee = await _employee(db, company)
    policy = CompanyPolicyDocument(
        id=uuid.uuid4(), company_id=company.id, title="Disciplinary Standing Orders",
        category="COMPLIANCE", raw_content="Fallback unpublished text", status="PUBLISHED", version_number="3.1",
    )
    db.add(policy)
    await db.flush()
    db.add(CompanyPolicyChunk(
        id=uuid.uuid4(), policy_document_id=policy.id, chunk_order=0, vector=[],
        chunk_text="For alleged misconduct, issue a show-cause notice and conduct an impartial inquiry before deciding the allegation.",
    ))
    db.add(CompanyPolicyDocument(
        id=uuid.uuid4(), company_id=other.id, title="Other Tenant Handbook", category="COMPLIANCE",
        raw_content="Other tenant secret misconduct clause", status="PUBLISHED",
    ))
    db.add(GrievanceCase(
        id=uuid.uuid4(), company_id=company.id, case_number="GRV-RESOLVED-1",
        reporter_employee_id=employee.id, category="MISCONDUCT", subject="Access card misuse",
        description="Confidential narrative must not be copied", accused_user_ids=[], status="RESOLVED",
        sla_due_at=datetime.now(UTC), resolution="Written warning after inquiry", resolved_at=datetime.now(UTC),
    ))
    await db.commit()
    result = await _copilot(db).disciplinary_case_assistant(
        company_id=company.id, employee_id=employee.id,
        incident_summary="Alleged access card misuse at the office entrance",
        incident_date="2026-10-01", policy_query="misconduct show cause impartial inquiry",
    )
    assert result["grounding_status"] == "GROUNDED"
    assert result["policy_citations"][0]["document"] == "Disciplinary Standing Orders"
    assert "show-cause" in result["show_cause_notice"].lower()
    assert "impartial inquiry" in result["show_cause_notice"]
    assert len(result["inquiry_checklist"]) >= 5
    assert result["precedent_comparisons"][0]["case_number"] == "GRV-RESOLVED-1"
    assert "Confidential narrative" not in str(result)
    assert "Other Tenant Handbook" not in str(result)
    with pytest.raises(LookupError):
        await _copilot(db).disciplinary_case_assistant(
            company_id=other.id, employee_id=employee.id,
            incident_summary="Cross tenant attempt", incident_date="2026-10-01",
        )


@pytest.mark.asyncio
async def test_disciplinary_assistant_requires_published_policy_evidence(db):
    company = await _company(db)
    employee = await _employee(db, company)
    db.add(CompanyPolicyDocument(
        id=uuid.uuid4(), company_id=company.id, title="Draft Handbook", category="COMPLIANCE",
        raw_content="Unpublished misconduct rule", status="DRAFT",
    ))
    await db.commit()
    result = await _copilot(db).disciplinary_case_assistant(
        company_id=company.id, employee_id=employee.id,
        incident_summary="Alleged misuse of a company access card", incident_date="2026-10-01",
    )
    assert result["grounding_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["policy_citations"] == []
    assert "INSERT VERIFIED POLICY CLAUSE" in result["show_cause_notice"]
    assert result["warnings"]


@pytest.mark.asyncio
async def test_termination_risk_protections_and_exact_compensation(db):
    company = await _company(db)
    user = await _user(db, company)
    employee = await _employee(
        db, company, user_id=user.id, joining_date=date(2020, 1, 1),
        employee_category="WORKMAN", role_metadata={"maternity_protected": True},
    )
    db.add(Compensation(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
        ctc_annual_paise=120_000_000, basic_monthly_paise=5_000_000,
        hra_monthly_paise=2_000_000, special_allowance_monthly_paise=3_000_000,
        effective_date=date(2025, 1, 1), status="ACTIVE",
    ))
    db.add(GrievanceCase(
        id=uuid.uuid4(), company_id=company.id, case_number="GRV-ACTIVE-1",
        reporter_employee_id=employee.id, category="HARASSMENT", subject="Protected complaint",
        description="Active case", accused_user_ids=[], status="INQUIRY",
        sla_due_at=datetime.now(UTC) + timedelta(days=30),
    ))
    await db.commit()
    result = await _copilot(db).termination_risk_assistant(
        company_id=company.id, employee_id=employee.id, termination_reason="Retrenchment due to redundancy",
        proposed_last_working_date=date(2026, 2, 1), notice_period_days=30,
        notice_days_served=10, maternity_protected=False, is_workman=False,
        as_of_date=date(2026, 1, 1),
    )
    assert result["protected_employment_flags"] == {
        "maternity_protected": True, "active_posh_or_grievance": True,
        "active_case_count": 1, "is_workman": True,
    }
    assert result["notice"]["compensation_paise"] == 6_666_667
    assert result["retrenchment"]["compensation_paise"] == 30_000_000
    assert result["risk_level"] == "CRITICAL"
    assert result["requires_legal_review"] is True
    assert any("independent POSH/grievance" in item for item in result["mitigation_checklist"])


@pytest.mark.asyncio
async def test_culture_analytics_department_indices_and_coverage(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    employee = await _employee(db, company, department="Engineering")
    await _employee(db, other, department="Engineering")
    survey = EngagementSurvey(
        id=uuid.uuid4(), company_id=company.id, title="Pulse", starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=1), status="ACTIVE", is_anonymous=False, min_group_size=1,
    )
    db.add(survey)
    await db.flush()
    nps = EngagementQuestion(id=uuid.uuid4(), company_id=company.id, survey_id=survey.id, question_text="Recommend us as an employer?", question_type="ENPS", sequence_number=1)
    pulse = EngagementQuestion(id=uuid.uuid4(), company_id=company.id, survey_id=survey.id, question_text="How are you feeling?", question_type="RATING", sequence_number=2)
    response = EngagementResponse(id=uuid.uuid4(), company_id=company.id, survey_id=survey.id, employee_id=employee.id, respondent_key_hash="a" * 64, department="Engineering", submitted_at=datetime.now(UTC))
    db.add_all([nps, pulse, response])
    await db.flush()
    db.add_all([
        EngagementAnswer(id=uuid.uuid4(), company_id=company.id, response_id=response.id, question_id=nps.id, numeric_value=10),
        EngagementAnswer(id=uuid.uuid4(), company_id=company.id, response_id=response.id, question_id=pulse.id, numeric_value=4),
        OvertimeEntry(id=uuid.uuid4(), company_id=company.id, employee_id=employee.id, period_month=10, period_year=2026, ot_hours=Decimal("20"), status="APPROVED"),
        EmployeeLeavePolicy(id=uuid.uuid4(), employee_id=employee.id, leave_type="ANNUAL", total_days=20, used_days=5, effective_from=date(2026, 1, 1)),
        SupportTicket(id=uuid.uuid4(), company_id=company.id, employee_id=employee.id, category="HR", title="Great helpful support", description="Resolved quickly and excellent", status="CLOSED"),
    ])
    await db.commit()
    result = await HRDifferentiatorAnalytics(db).culture(company.id)
    row = result["departments"][0]
    assert row["department"] == "Engineering" and row["headcount"] == 1
    assert row["enps"] == 100 and row["pulse_average"] == 4
    assert row["leave_utilization_pct"] == 25
    assert row["average_overtime_hours_per_employee"] == 20
    assert row["helpdesk_sentiment"] > 0
    assert 0 <= row["culture_index"] <= 100 and 0 <= row["burnout_index"] <= 100
    assert result["organization"]["headcount"] == 1


@pytest.mark.asyncio
async def test_diversity_analytics_consent_leadership_grades_and_funnel(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    female_manager = await _employee(db, company, designation="Engineering Manager", gender="FEMALE", date_of_birth=date(1985, 1, 1))
    male_engineer = await _employee(db, company, designation="Engineer", gender="MALE", date_of_birth=date(1998, 1, 1))
    await _employee(db, other, designation="Director", gender="FEMALE")
    band = await _band(db, company, grade="L5")
    await _assignment(db, company, female_manager, band, annual=10_000_000)
    await _assignment(db, company, male_engineer, band, annual=8_000_000)
    job, other_job = await _job(db, company), await _job(db, other)
    await _application(db, company, job, gender="FEMALE", consented=True, status="HIRED")
    await _application(db, company, job, gender="MALE", consented=True, status="APPLIED")
    await _application(db, company, job, gender="FEMALE", consented=False, status="APPLIED")
    await _application(db, other, other_job, gender="FEMALE", consented=True, status="HIRED")
    await db.commit()
    result = await HRDifferentiatorAnalytics(db).diversity(company.id)
    assert result["headcount"] == 2
    assert result["grade"]["L5"]["count"] == 2
    assert result["leadership"]["women_leadership_ratio_pct"] == 100
    assert result["hiring_funnel_parity"]["total_applicants"] == 3
    assert result["hiring_funnel_parity"]["disclosed_applicants"] == 2
    rows = {row["gender"]: row for row in result["hiring_funnel_parity"]["rows"]}
    assert rows["FEMALE"]["hired"] == 1
    assert rows["NOT_DISCLOSED"]["applicants"] == 1
    assert "never inferred" in result["privacy_note"]


@pytest.mark.asyncio
async def test_attrition_risk_explanations_playbook_and_snapshot_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    manager = await _employee(db, company, designation="Manager", joining_date=date(2018, 1, 1))
    employee = await _employee(
        db, company, manager_id=manager.id, joining_date=date(2020, 1, 1),
        last_promotion_date=date(2020, 1, 1),
    )
    await _employee(db, company, manager_id=manager.id, joining_date=date(2020, 1, 1), status="TERMINATED")
    band = await _band(db, company)
    await _assignment(db, company, employee, band, annual=7_000_000)
    await db.commit()
    result = await HRDifferentiatorAnalytics(db).attrition_risk(
        company.id, as_of_date=date(2026, 10, 1), persist=True,
    )
    target = next(row for row in result["employees"] if row["employee_id"] == str(employee.id))
    assert target["compa_ratio"] == 0.7
    assert target["manager_attrition_pct"] == 50
    assert target["months_since_promotion"] > 36
    assert target["flight_risk_score"] >= 55
    assert target["retention_playbook"]["retention_bonus"]["amount_paise"] > 0
    assert target["retention_playbook"]["internal_transfer"]["recommended"] is True
    assert len(target["retention_playbook"]["stay_interview"]["questions"]) == 3
    snapshots = (await db.execute(select(EmployeeRiskAssessment).where(EmployeeRiskAssessment.company_id == company.id))).scalars().all()
    assert snapshots and all(row.model_version == "BATCH7_DETERMINISTIC_V1" for row in snapshots)
    assert (await db.execute(select(EmployeeRiskAssessment).where(EmployeeRiskAssessment.company_id == other.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_workforce_planning_requisition_projection_and_monthly_burn(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    await _employee(db, company, department="Engineering")
    await _job(db, company, vacancies=2)
    await _job(db, other, vacancies=10)
    service = WorkforcePlanningService(db)
    plan = await service.upsert_plan(
        company_id=company.id, fiscal_year="2026-27", department="Engineering",
        approved_headcount=5, annual_hiring_budget_paise=12_000_000,
    )
    assert plan.status == "APPROVED"
    result = await service.planning(company_id=company.id, fiscal_year="2026-27")
    assert result["total_approved_headcount"] == 5 and result["total_actual_headcount"] == 1
    assert result["total_requisition_cost_projection_paise"] == 30_000_000
    burn = result["monthly_hiring_budget_burn"][0]
    assert burn["monthly_requisition_projection_paise"] == 2_500_000
    assert burn["monthly_hiring_budget_paise"] == 1_000_000
    assert burn["monthly_burn_rate_pct"] == 250
    assert burn["budget_status"] == "OVER_BUDGET"
    assert len(result["requisitions"]) == 1


@pytest.mark.asyncio
async def test_org_twin_all_five_simulations_persist_without_executing_changes(db):
    company = await _company(db)
    manager = await _employee(db, company, designation="Manager", ctc=100000)
    direct = await _employee(db, company, manager_id=manager.id, ctc=80000)
    db.add_all([
        EmployeeSkill(id=uuid.uuid4(), employee_id=manager.id, skill_name="Python", proficiency="EXPERT"),
        EmployeeSkill(id=uuid.uuid4(), employee_id=direct.id, skill_name="Python", proficiency="INTERMEDIATE"),
    ])
    await db.commit()
    service = OrgTwinSimulationService(db)
    scenarios = [
        ("BUDGET_CUT", {"cut_percentage": 10}, "target_reduction_paise"),
        ("KEY_PERSON_EXIT", {"key_employee_ids": [str(manager.id)]}, "key_person_impacts"),
        ("PROJECT_SKILLS", {"required_skills": {"python": 2, "kubernetes": 1}}, "project_readiness_pct"),
        ("SPAN_OF_CONTROL", {"minimum_direct_reports": 2, "maximum_direct_reports": 5}, "exceptions"),
        ("RESTRUCTURING", {"moves": [{"employee_id": str(direct.id), "to_department": "Platform"}]}, "department_headcount_after"),
    ]
    for index, (scenario, parameters, key) in enumerate(scenarios):
        result = await service.simulate(company_id=company.id, scenario_type=scenario, name=f"Scenario {index}", parameters=parameters)
        assert result.scenario_type == scenario and result.status == "COMPLETED"
        assert key in result.result_json["impact"]
        assert result.result_json["simulation_only"] is True
    assert (await db.execute(select(OrgTwinSimulation).where(OrgTwinSimulation.company_id == company.id))).scalars().all()
    assert (await db.execute(select(OrgTwinSimulation))).scalars().all().__len__() == 5
    await db.refresh(direct)
    assert direct.department == "Engineering" and direct.status == "ACTIVE"
    with pytest.raises(LookupError):
        await service.simulate(company_id=company.id, scenario_type="KEY_PERSON_EXIT", name="Cross tenant", parameters={"key_employee_ids": [str(uuid.uuid4())]})


@pytest.mark.asyncio
async def test_marketplace_encrypted_credentials_sync_health_and_tenant_isolation(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    service = MarketplaceService(db)
    assert set(CONNECTOR_CATALOG) == {"SLACK", "TEAMS", "BIOMETRIC_PUSH", "RAZORPAYX", "TALLY", "ZOHO", "GOOGLE_CALENDAR"}
    configured = await service.configure(
        company_id=company.id, connector_code="SLACK", enabled=True,
        credentials={"bot_token": "xoxb-test-secret", "signing_secret": "signing-test-secret"},
        config={"channel": "hr-announcements"},
    )
    assert configured["status"] == "ENABLED" and configured["credentials_configured"] is True
    assert "credentials" not in configured and "xoxb-test-secret" not in str(configured)
    ciphertext = (await db.execute(text("SELECT credentials_encrypted FROM marketplace_integrations"))).scalar_one()
    assert ciphertext.startswith("ofc360:v1:") and "xoxb-test-secret" not in ciphertext
    sync = await service.sync(company_id=company.id, connector_code="SLACK", payload={"records": [{"message": "test"}]})
    assert sync["status"] == "ACCEPTED" and sync["records_accepted"] == 1
    logs = await service.sync_logs(company_id=company.id, connector_code="SLACK")
    assert len(logs) == 1 and logs[0]["health"]["external_acknowledgement"] is False
    assert await service.list_integrations(other.id) == []
    with pytest.raises(LookupError):
        await service.set_enabled(company_id=other.id, connector_code="SLACK", enabled=False)
    await service.set_enabled(company_id=company.id, connector_code="SLACK", enabled=False)
    with pytest.raises(PermissionError):
        await service.sync(company_id=company.id, connector_code="SLACK", payload={"records": []})


@pytest.mark.asyncio
async def test_whitelabel_validation_branded_previews_and_payslip_currency(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    service = WhiteLabelService(db)
    result = await service.update(company.id, {
        "whitelabel_enabled": True, "custom_domain": "HR.Acme.example",
        "brand_display_name": "Acme People", "brand_primary_color": "#112233",
        "brand_secondary_color": "#ddeeff", "brand_logo_url": "/assets/acme-logo.png",
        "email_sender_name": "Acme HR", "email_sender_address": "hr@acme.example",
        "email_reply_to": "people@acme.example", "branded_pdf_header_text": "Acme confidential HR document",
    })
    assert result["custom_domain"] == "hr.acme.example"
    assert result["theme"]["primary_color"] == "#112233"
    assert result["email_sender"]["address"] == "hr@acme.example"
    pdf = await service.preview_pdf(company.id)
    assert pdf.startswith(b"%PDF")
    preview_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Acme People" in preview_text and "Acme confidential HR document" in preview_text
    payslip_pdf = PayslipService._render_pdf(
        "Payslip", [("Basic", "1000.00")], [("Net Pay", "900.00")],
        branding=service.branding_for(await db.get(Company, company.id)), currency="USD",
    )
    payslip_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(payslip_pdf)).pages)
    assert "Acme People" in payslip_text and "USD" in payslip_text
    with pytest.raises(ValueError):
        await service.update(other.id, {"custom_domain": "hr.acme.example"})
    with pytest.raises(ValueError):
        await service.update(company.id, {"brand_logo_url": "javascript:alert(1)"})


@pytest.mark.asyncio
async def test_global_payroll_snapshots_country_calculators_and_compensation_rounding(db):
    company, other = await _company(db), await _company(db, "Other Tenant")
    period, other_period = await _period(db, company), await _period(db, other)
    rules = {
        "version": "US-TEST-2026.1",
        "employee_components": [{"code": "SOCIAL_SECURITY", "rate": "0.062"}],
        "employer_components": [{"code": "SOCIAL_SECURITY", "rate": "0.062"}],
    }
    run = await PayrollRunService.create_run(
        db, period.id, currency="USD", country_code="US", fx_rate_to_base="83.25",
        fx_rate_source="TEST_MANUAL_RATE", fx_rate_as_of=datetime(2026, 1, 31, tzinfo=UTC),
        statutory_rules=rules,
    )
    assert run.currency == "USD" and run.base_currency == "INR" and run.country_code == "US"
    assert run.fx_rate_to_base == Decimal("83.25000000")
    assert run.fx_rate_locked_at is not None
    assert run.fx_rate_snapshot["rate_to_base"] == "83.25000000"
    assert run.statutory_rules_snapshot == rules and run.statutory_rule_version == "US-TEST-2026.1"
    assert run.total_gross_base_paise == run.total_net_base_paise == 0
    with pytest.raises(HTTPException) as cross_tenant_error:
        await PayrollRunService.create_run(db, other_period.id, company_id=company.id, currency="USD", fx_rate_to_base="83.25")
    assert cross_tenant_error.value.status_code == 404
    with pytest.raises(HTTPException) as missing_fx_error:
        await PayrollRunService.create_run(db, period.id, currency="EUR")
    assert missing_fx_error.value.status_code == 422
    assert SUPPORTED_CURRENCIES == {"INR", "USD", "GBP", "EUR", "AED", "SGD"}
    calculator = get_country_statutory_calculator("US")
    calculation = calculator.calculate(CountryStatutoryInput("US", "USD", 100000, 50000, 1, 2026, rules))
    assert calculation.employee_deductions_paise == 6200
    assert calculation.employer_contributions_paise == 6200
    assert calculation.components == {"EMPLOYEE:SOCIAL_SECURITY": 6200, "EMPLOYER:SOCIAL_SECURITY": 6200}
    unconfigured = get_country_statutory_calculator("AE").calculate(CountryStatutoryInput("AE", "AED", 100000, 50000, 1, 2026, {}))
    assert unconfigured.review_required is True and unconfigured.employee_deductions_paise == 0
    assert unconfigured.warnings
    assert convert_minor_units(101, "0.5") == 51
    employee = await _employee(db, company)
    comp = await PayrollCompensationService.assign_or_update_compensation(
        db, employee.id, 1_000_001, currency="USD", fx_rate_to_inr="83.25", effective_date=date(2026, 1, 1),
    )
    assert comp.currency == "USD" and comp.fx_rate_to_inr == Decimal("83.25000000")
    assert convert_minor_units(comp.ctc_annual_paise, comp.fx_rate_to_inr) == 83_250_083


@pytest.mark.asyncio
async def test_global_payroll_executes_end_to_end_with_country_components_and_base_totals(db):
    company = await _company(db)
    employee = await _employee(db, company)
    period = await _period(db, company)
    db.add(Compensation(
        id=uuid.uuid4(), company_id=company.id, employee_id=employee.id,
        ctc_annual_paise=1_200_000, basic_monthly_paise=50_000,
        hra_monthly_paise=20_000, special_allowance_monthly_paise=30_000,
        currency="USD", fx_rate_to_inr=Decimal("83.25"),
        effective_date=date(2025, 1, 1), status="ACTIVE",
    ))
    await db.commit()
    rules = {
        "version": "US-EXECUTION-TEST-2026.1",
        "employee_components": [{"code": "SOCIAL_SECURITY", "rate": "0.062"}],
        "employer_components": [{"code": "SOCIAL_SECURITY", "rate": "0.062"}],
    }
    run = await PayrollRunService.create_run(
        db, period.id, currency="USD", country_code="US", fx_rate_to_base="83.25",
        statutory_rules=rules,
    )
    assert run.status == "VALIDATED"
    await PayrollRunService.execute_run_calculation(db, run.id, company_id=company.id)
    await db.refresh(run)
    run_employee = (await db.execute(select(PayrollRunEmployee).where(
        PayrollRunEmployee.run_id == run.id, PayrollRunEmployee.employee_id == employee.id,
    ))).scalar_one()
    payslip = (await db.execute(select(Payslip).where(
        Payslip.payroll_run_id == run.id, Payslip.employee_id == employee.id,
    ))).scalar_one()

    assert run.status == "PROCESSED" and run.total_employees == 1
    assert run.validation_status == "VALID"
    assert (run.total_gross_paise, run.total_deductions_paise, run.total_net_paise) == (100_000, 6_200, 93_800)
    assert (run.total_gross_base_paise, run.total_deductions_base_paise, run.total_net_base_paise) == (8_325_000, 516_150, 7_808_850)
    assert (run_employee.gross_base_paise, run_employee.total_deductions_base_paise, run_employee.net_base_paise) == (8_325_000, 516_150, 7_808_850)
    assert run_employee.earnings_breakup["basic_paise"] == 50_000
    deductions = run_employee.deductions_breakup
    assert deductions["country_statutory_components_paise"] == {
        "EMPLOYEE:SOCIAL_SECURITY": 6_200, "EMPLOYER:SOCIAL_SECURITY": 6_200,
    }
    assert deductions["country_employee_deductions_paise"] == 6_200
    assert deductions["country_employer_contributions_paise"] == 6_200
    assert deductions["statutory_review_required"] is False
    assert all(deductions[key] == 0 for key in ("pf_paise", "esi_paise", "pt_paise", "lwf_paise", "tds_paise"))
    assert payslip.currency == "USD"
    assert payslip.gross_earnings == Decimal("1000.00")
    assert payslip.total_deductions == Decimal("62.00")
    assert payslip.net_pay == Decimal("938.00")
    assert (payslip.gross_base_paise, payslip.total_deductions_base_paise, payslip.net_base_paise) == (8_325_000, 516_150, 7_808_850)

    review_period = await _period(db, company, month=2)
    review_run = await PayrollRunService.create_run(
        db, review_period.id, currency="AED", country_code="AE", fx_rate_to_base="22.50",
    )
    await PayrollRunService.execute_run_calculation(db, review_run.id, company_id=company.id)
    await db.refresh(review_run)
    review_employee = (await db.execute(select(PayrollRunEmployee).where(
        PayrollRunEmployee.run_id == review_run.id, PayrollRunEmployee.employee_id == employee.id,
    ))).scalar_one()
    assert review_employee.gross_earnings_paise == 370_000
    assert review_employee.gross_base_paise == 8_325_000
    assert review_employee.deductions_breakup["statutory_review_required"] is True
    assert review_employee.deductions_breakup["statutory_warnings"]
    assert review_employee.deductions_breakup["country_employee_deductions_paise"] == 0
    assert review_run.validation_status == "WARNING"
    assert any(issue.get("code") == "COUNTRY_STATUTORY_REVIEW_REQUIRED" for issue in review_run.validation_errors)


def test_batch7_routes_and_global_response_contracts():
    from app.api.v2.router import v2_router
    from app.schemas.payroll_v2.compensation import CompensationResponse
    from app.schemas.payroll_v2.runs import PayrollRunEmployeeResponse, PayrollRunResponse

    def paths(router, prefix=""):
        for route in router.routes:
            if hasattr(route, "path"):
                yield prefix + route.path
            elif hasattr(route, "original_router"):
                yield from paths(route.original_router, prefix + route.include_context.prefix)

    registered = set(paths(v2_router))
    required = {
        "/api/v2/ai/salary-negotiation-copilot", "/api/v2/ai/disciplinary-assistant",
        "/api/v2/ai/termination-risk-assistant", "/api/v2/analytics/culture",
        "/api/v2/analytics/diversity", "/api/v2/analytics/attrition-risk",
        "/api/v2/workforce/planning", "/api/v2/org-twin/simulate",
        "/api/v2/marketplace/catalog", "/api/v2/whitelabel",
    }
    assert not required - registered
    assert {"currency", "base_currency", "fx_rate_snapshot", "fx_rate_locked_at", "statutory_rule_version", "total_net_base_paise"} <= set(PayrollRunResponse.model_fields)
    assert {"gross_base_paise", "total_deductions_base_paise", "net_base_paise"} <= set(PayrollRunEmployeeResponse.model_fields)
    assert {"currency", "fx_rate_to_inr", "ctc_annual_inr_paise", "basic_monthly_inr_paise"} <= set(CompensationResponse.model_fields)
