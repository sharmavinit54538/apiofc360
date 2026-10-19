"""Unit and integration tests for Recruitment Analytics API, Service, and Schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.auth import get_current_user_claims
from app.schemas.recruitment import (
    ApplicantAnalyticsMetrics,
    ConversionRates,
    DepartmentRecruitmentMetric,
    FunnelStage,
    JobAnalyticsMetrics,
    PipelineBreakdown,
    RecruitmentAnalyticsResponse,
    SourceRecruitmentMetric,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service


# ---------------------------------------------------------------------------
# 1. Pydantic Schemas Tests
# ---------------------------------------------------------------------------

def test_recruitment_analytics_response_defaults():
    """Verify that RecruitmentAnalyticsResponse initializes properly with defaults."""
    response = RecruitmentAnalyticsResponse(
        jobs=JobAnalyticsMetrics(),
        applicants=ApplicantAnalyticsMetrics(),
        pipeline=PipelineBreakdown(),
        conversion_rates=ConversionRates(),
    )
    assert response.jobs.total_jobs == 0
    assert response.jobs.active_jobs == 0
    assert response.applicants.total_candidates == 0
    assert response.applicants.total_applications == 0
    assert response.pipeline.applied == 0
    assert response.pipeline.hired == 0
    assert response.conversion_rates.application_to_shortlist_rate == 0.0
    assert response.conversion_rates.avg_time_to_hire_days is None
    assert response.funnel == []
    assert response.department_breakdown == []
    assert response.source_breakdown == []


def test_recruitment_analytics_response_populated():
    """Verify serialization of complete recruitment analytics schema."""
    response = RecruitmentAnalyticsResponse(
        jobs=JobAnalyticsMetrics(
            total_jobs=10,
            active_jobs=6,
            draft_jobs=2,
            closed_jobs=2,
            total_requisitions=5,
            active_requisitions=3,
            pending_requisitions=1,
            closed_requisitions=1,
            total_vacancies=15,
        ),
        applicants=ApplicantAnalyticsMetrics(
            total_candidates=100,
            total_applications=120,
            talent_pool_candidates=25,
            applications_today=5,
            applications_this_month=40,
        ),
        pipeline=PipelineBreakdown(
            applied=50,
            shortlisted=20,
            interviewed=15,
            offered=8,
            hired=5,
            rejected=22,
        ),
        conversion_rates=ConversionRates(
            application_to_shortlist_rate=40.0,
            shortlist_to_interview_rate=50.0,
            interview_to_offer_rate=40.0,
            offer_acceptance_rate=62.5,
            overall_hire_rate=4.17,
            avg_time_to_hire_days=18.5,
            avg_time_to_fill_days=25.0,
        ),
        funnel=[
            FunnelStage(stage="Applied", count=120, conversion_rate=100.0),
            FunnelStage(stage="Shortlisted", count=48, conversion_rate=40.0),
            FunnelStage(stage="Interview", count=28, conversion_rate=58.33),
            FunnelStage(stage="Offer", count=13, conversion_rate=46.43),
            FunnelStage(stage="Hired", count=5, conversion_rate=38.46),
        ],
        department_breakdown=[
            DepartmentRecruitmentMetric(
                department="Engineering",
                total_jobs=5,
                active_jobs=3,
                total_applications=80,
                hired_count=4,
            )
        ],
        source_breakdown=[
            SourceRecruitmentMetric(
                source="LINKEDIN",
                candidate_count=60,
                percentage=60.0,
            )
        ],
    )

    data = response.model_dump()
    assert data["jobs"]["total_jobs"] == 10
    assert data["jobs"]["active_jobs"] == 6
    assert data["applicants"]["total_applications"] == 120
    assert data["pipeline"]["hired"] == 5
    assert data["conversion_rates"]["avg_time_to_hire_days"] == 18.5
    assert len(data["funnel"]) == 5
    assert data["department_breakdown"][0]["department"] == "Engineering"
    assert data["source_breakdown"][0]["source"] == "LINKEDIN"


# ---------------------------------------------------------------------------
# 2. Service Logic Unit Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recruitment_service_analytics_calculation():
    """Verify Service aggregation computation, funnel progression, conversion rates, and time-to-hire."""
    mock_session = AsyncMock()
    mock_repo = MagicMock()
    mock_auth_repo = MagicMock()
    mock_emp_repo = MagicMock()
    mock_email_svc = MagicMock()

    # Synthetic timestamps for time to hire calculation: 10 days and 20 days duration
    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=10)
    t2 = t0 + timedelta(days=20)

    # Mock database aggregated row returns from repo
    mock_job_row = MagicMock(
        total_jobs=12,
        active_jobs=8,
        draft_jobs=2,
        closed_jobs=2,
        total_vacancies=20,
    )
    mock_req_row = MagicMock(
        total_requisitions=6,
        active_requisitions=4,
        pending_requisitions=1,
        closed_requisitions=1,
    )
    mock_app_summary = MagicMock(
        total_applications=100,
        applications_today=3,
        applications_this_month=25,
        unique_applicants=85,
    )
    mock_cand_row = MagicMock(
        total_candidates=90,
        talent_pool_candidates=15,
    )

    mock_dept_row = MagicMock(
        department="Product",
        total_jobs=3,
        active_jobs=2,
        total_applications=30,
        hired_count=2,
    )
    mock_source_row = MagicMock(
        source="Direct",
        source_count=50,
    )

    mock_repo.get_recruitment_analytics_data = AsyncMock(
        return_value={
            "job_row": mock_job_row,
            "req_row": mock_req_row,
            "status_counts": {
                "APPLIED": 40,
                "UNDER_REVIEW": 10,
                "SHORTLISTED": 20,
                "INTERVIEW_SCHEDULED": 10,
                "INTERVIEW_COMPLETED": 5,
                "SELECTED": 0,
                "OFFER_SENT": 5,
                "OFFER_ACCEPTED": 2,
                "EMPLOYEE_CREATED": 0,
                "REJECTED": 8,
            },
            "app_summary_row": mock_app_summary,
            "cand_row": mock_cand_row,
            "source_rows": [mock_source_row],
            "dept_rows": [mock_dept_row],
            "hired_rows": [(t0, t1), (t0, t2)],
        }
    )

    service = RecruitmentService(
        session=mock_session,
        repo=mock_repo,
        auth_repo=mock_auth_repo,
        employee_repo=mock_emp_repo,
        email_service=mock_email_svc,
    )

    company_id = uuid.uuid4()
    result = await service.get_recruitment_analytics(company_id=company_id)

    # Assert repository was called with multi-tenancy filter
    mock_repo.get_recruitment_analytics_data.assert_awaited_once_with(
        company_id=company_id,
        start_date=None,
        end_date=None,
        department=None,
        job_id=None,
    )

    # Verify metrics
    assert result.jobs.total_jobs == 12
    assert result.jobs.active_jobs == 8
    assert result.jobs.total_requisitions == 6
    assert result.jobs.total_vacancies == 20

    assert result.applicants.total_applications == 100
    assert result.applicants.total_candidates == 90
    assert result.applicants.talent_pool_candidates == 15

    # Pipeline breakdown
    assert result.pipeline.applied == 50  # 40 applied + 10 under_review
    assert result.pipeline.shortlisted == 20
    assert result.pipeline.interviewed == 15  # 10 scheduled + 5 completed
    assert result.pipeline.offered == 5
    assert result.pipeline.hired == 2
    assert result.pipeline.rejected == 8

    # Time to hire: (10 + 20) / 2 = 15.0 days
    assert result.conversion_rates.avg_time_to_hire_days == 15.0

    # Progressive conversion rates
    # stage_applied = 100
    # stage_shortlisted = 20 + 15 + 5 + 2 = 42
    # stage_interview = 15 + 5 + 2 = 22
    # stage_offer = 5 + 2 = 7
    # stage_hired = 2
    assert result.conversion_rates.application_to_shortlist_rate == 42.0
    assert result.conversion_rates.shortlist_to_interview_rate == round((22 / 42) * 100, 2)
    assert result.conversion_rates.interview_to_offer_rate == round((7 / 22) * 100, 2)
    assert result.conversion_rates.offer_acceptance_rate == round((2 / 7) * 100, 2)
    assert result.conversion_rates.overall_hire_rate == 2.0


@pytest.mark.asyncio
async def test_recruitment_service_analytics_empty_data():
    """Verify Service handles empty dataset gracefully without division by zero."""
    mock_session = AsyncMock()
    mock_repo = MagicMock()

    mock_repo.get_recruitment_analytics_data = AsyncMock(
        return_value={
            "job_row": MagicMock(total_jobs=0, active_jobs=0, draft_jobs=0, closed_jobs=0, total_vacancies=0),
            "req_row": MagicMock(total_requisitions=0, active_requisitions=0, pending_requisitions=0, closed_requisitions=0),
            "status_counts": {},
            "app_summary_row": MagicMock(total_applications=0, applications_today=0, applications_this_month=0, unique_applicants=0),
            "cand_row": MagicMock(total_candidates=0, talent_pool_candidates=0),
            "source_rows": [],
            "dept_rows": [],
            "hired_rows": [],
        }
    )

    service = RecruitmentService(
        session=mock_session,
        repo=mock_repo,
        auth_repo=MagicMock(),
        employee_repo=MagicMock(),
        email_service=MagicMock(),
    )

    result = await service.get_recruitment_analytics()

    assert result.jobs.total_jobs == 0
    assert result.applicants.total_applications == 0
    assert result.pipeline.applied == 0
    assert result.conversion_rates.application_to_shortlist_rate == 0.0
    assert result.conversion_rates.overall_hire_rate == 0.0
    assert result.conversion_rates.avg_time_to_hire_days is None
    assert result.funnel[0].count == 0


# ---------------------------------------------------------------------------
# 3. FastAPI Route Integration & RBAC Tests
# ---------------------------------------------------------------------------

def test_recruitment_analytics_rbac_hr_admin_authorized():
    """Verify that users with hr_admin role are granted access to /analytics."""
    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    claims = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "hr_admin",
        "type": "access",
    }

    mock_service = AsyncMock()
    mock_service.get_recruitment_analytics.return_value = RecruitmentAnalyticsResponse(
        jobs=JobAnalyticsMetrics(total_jobs=5, active_jobs=3),
        applicants=ApplicantAnalyticsMetrics(total_applications=20, total_candidates=18),
        pipeline=PipelineBreakdown(applied=10, shortlisted=5, interviewed=3, offered=1, hired=1),
        conversion_rates=ConversionRates(avg_time_to_hire_days=14.0),
    )

    app.dependency_overrides[get_current_user_claims] = lambda: claims
    app.dependency_overrides[get_recruitment_service] = lambda: mock_service

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/recruitment/analytics")
            assert response.status_code == 200
            json_data = response.json()
            assert json_data["success"] is True
            assert json_data["data"]["jobs"]["total_jobs"] == 5
            assert json_data["data"]["applicants"]["total_applications"] == 20
            assert json_data["data"]["conversion_rates"]["avg_time_to_hire_days"] == 14.0

            # Test alternative route /recruitment-analytics
            alt_res = client.get("/api/v1/recruitment/recruitment-analytics")
            assert alt_res.status_code == 200
            assert alt_res.json()["success"] is True
    finally:
        app.dependency_overrides.pop(get_current_user_claims, None)
        app.dependency_overrides.pop(get_recruitment_service, None)


def test_recruitment_analytics_rbac_employee_forbidden():
    """Verify that unauthorized roles (e.g. employee) are blocked with 403 Forbidden."""
    user_id = uuid.uuid4()
    claims = {
        "sub": str(user_id),
        "company_id": str(uuid.uuid4()),
        "role": "employee",
        "type": "access",
    }

    app.dependency_overrides[get_current_user_claims] = lambda: claims

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/recruitment/analytics")
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user_claims, None)


def test_recruitment_analytics_query_filters():
    """Verify that query parameters (department, job_id, dates) are parsed and passed to service."""
    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    job_uuid = uuid.uuid4()
    claims = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "super_admin",
        "type": "access",
    }

    mock_service = AsyncMock()
    mock_service.get_recruitment_analytics.return_value = RecruitmentAnalyticsResponse(
        jobs=JobAnalyticsMetrics(total_jobs=1),
        applicants=ApplicantAnalyticsMetrics(total_applications=5),
        pipeline=PipelineBreakdown(),
        conversion_rates=ConversionRates(),
    )

    app.dependency_overrides[get_current_user_claims] = lambda: claims
    app.dependency_overrides[get_recruitment_service] = lambda: mock_service

    try:
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/recruitment/analytics?department=Engineering&job_id={job_uuid}&start_date=2026-01-01&end_date=2026-03-31"
            )
            assert response.status_code == 200
            mock_service.get_recruitment_analytics.assert_awaited_once_with(
                company_id=company_id,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
                department="Engineering",
                job_id=job_uuid,
            )
    finally:
        app.dependency_overrides.pop(get_current_user_claims, None)
        app.dependency_overrides.pop(get_recruitment_service, None)
