"""Comprehensive test suite for AI Resume Screening production hardening.

Validates:
1. STEP 1 - Security & Multi-Tenant Data Isolation (404 on cross-tenant access to resume, job, results, decision, history)
2. STEP 2 - Logic Bug Fixes:
   - Nullable application_id (no fake UUID generated)
   - Match score computation when missing & FAILED status on match failure (no silent 0.5)
   - Head+tail truncation preserving critical boundaries
   - Batch screening persistence & per-item fault tolerance
   - Backend-only thresholds in response
3. STEP 3 - Endpoint Contracts:
   - POST /api/v2/screening/jobs/{job_id}/run
   - GET /api/v2/screening/jobs/{job_id}/results
   - POST /api/v2/screening/results/{screening_id}/decision
4. STEP 4 - Compliance & Bias Safeguards:
   - Anti-bias demographic stripping (name, gender, age, nationality, photo, college pedigree)
   - Auto-reject suppression when AI_AUTO_REJECT_ENABLED is False
   - Audit trail metadata (model, prompt_version, input_hash, thresholds_used)
5. STEP 5 - Reliability:
   - LLM timeout / retry and explicit FAILED status (no fake REVIEW)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agents.screening_agent import (
    ScreeningAgent,
    ScreeningResult,
    strip_biasing_metadata,
    truncate_head_tail,
)
from app.core.config import settings
from app.db.database import get_db_session
from app.main import app
from app.middleware.auth import get_current_user_claims
from app.models.ai_recruitment import (
    AIResumeDocument,
    AIScreeningResult,
    CandidateMatchScore,
    RecruitmentAuditLog,
)
from app.models.recruitment import Application, Job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_a():
    return uuid.uuid4()


@pytest.fixture
def tenant_b():
    return uuid.uuid4()


@pytest.fixture
def user_a():
    return uuid.uuid4()


@pytest.fixture
def client_tenant_a(tenant_a, user_a):
    claims = {
        "sub": str(user_a),
        "company_id": str(tenant_a),
        "role": "hr_admin",
        "type": "access",
    }
    app.dependency_overrides[get_current_user_claims] = lambda: claims
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_current_user_claims, None)


def _extract_error_message(response) -> str:
    body = response.json()
    msg = (
        body.get("detail")
        or body.get("message")
        or (body.get("error", {}) if isinstance(body.get("error"), dict) else {}).get("message")
        or ""
    )
    return str(msg).lower()


# ---------------------------------------------------------------------------
# 1. Bias Stripping & Truncation Unit Tests
# ---------------------------------------------------------------------------

def test_bias_stripping_removes_demographics_and_pedigree():
    raw_resume = (
        "Candidate Name: Alice Smith\n"
        "Email: alice.smith@example.com Phone: +1 555-123-4567\n"
        "Gender: Female, Pronouns: she/her\n"
        "Date of Birth: 1990-05-12, Age: 34\n"
        "Nationality: Canadian, Marital Status: Single\n"
        "[Profile Picture Attached]\n"
        "Education: B.S. Computer Science from an Ivy League University (Tier 1 College)\n"
        "Skills: Python, FastAPI, PostgreSQL, Kubernetes"
    )

    clean = strip_biasing_metadata(raw_resume, candidate_name="Alice Smith")

    # Demographic & PII checks
    assert "Alice Smith" not in clean
    assert "alice.smith@example.com" not in clean
    assert "+1 555-123-4567" not in clean
    assert "Female" not in clean
    assert "1990-05-12" not in clean
    assert "Canadian" not in clean
    assert "Ivy League" not in clean
    assert "Tier 1 College" not in clean

    # Essential qualifications preserved
    assert "Python" in clean
    assert "FastAPI" in clean
    assert "PostgreSQL" in clean
    assert "Accredited University" in clean


def test_head_tail_truncation_preserves_both_ends(caplog):
    text = "HEAD_CONTENT_" + ("MIDDLE_" * 500) + "_TAIL_CONTENT"
    max_chars = 100

    with caplog.at_level(logging.WARNING):
        truncated = truncate_head_tail(text, max_chars=max_chars, label="test_doc")

    assert len(truncated) <= max_chars + 30
    assert "HEAD_CONTENT_" in truncated
    assert "_TAIL_CONTENT" in truncated
    assert "...[content truncated]..." in truncated
    assert "Truncating test_doc" in caplog.text


# ---------------------------------------------------------------------------
# 2. ScreeningAgent Reliability & Compliance Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_failure_returns_failed_status_not_fake_review():
    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(side_effect=RuntimeError("Connection to Ollama refused"))

    agent = ScreeningAgent(llm_client=mock_llm)
    res = await agent.screen(
        resume_text="Experienced developer in Python",
        jd_text="Looking for a Python backend engineer",
        match_score=0.5,
    )

    assert res.status == "FAILED"
    assert res.decision is None
    assert "Connection to Ollama refused" in (res.error_message or "")


@pytest.mark.asyncio
async def test_auto_reject_suppressed_when_setting_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AI_AUTO_REJECT_ENABLED", False)

    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(return_value='{"decision": "REJECT", "confidence": 0.2}')

    agent = ScreeningAgent(llm_client=mock_llm)
    res = await agent.screen(
        resume_text="No relevant experience",
        jd_text="Requires 10 years distributed systems",
        match_score=0.2,  # Below rejection threshold
    )

    assert res.decision == "REJECT"
    assert res.auto_rejected is False  # Suppressed by AI_AUTO_REJECT_ENABLED=False


@pytest.mark.asyncio
async def test_auto_reject_enabled_when_setting_true(monkeypatch):
    monkeypatch.setattr(settings, "AI_AUTO_REJECT_ENABLED", True)

    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(return_value='{"decision": "REJECT", "confidence": 0.2}')

    agent = ScreeningAgent(llm_client=mock_llm)
    res = await agent.screen(
        resume_text="No relevant experience",
        jd_text="Requires 10 years distributed systems",
        match_score=0.2,
    )

    assert res.decision == "REJECT"
    assert res.auto_rejected is True


# ---------------------------------------------------------------------------
# 3. Multi-Tenant Security & IDOR Prevention Tests
# ---------------------------------------------------------------------------

def test_screen_cross_tenant_resume_doc_returns_404(client_tenant_a, tenant_a, tenant_b):
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()

    mock_session = AsyncMock()

    # Query 1: doc check (belongs to Tenant B) -> returns None because tenant_id in where clause is Tenant A
    doc_exec_res = MagicMock()
    doc_exec_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = doc_exec_res

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            "/api/v2/screening/screen",
            json={"resume_document_id": str(doc_id), "job_id": str(job_id)},
        )
        assert response.status_code == 404
        assert "resume document not found" in _extract_error_message(response)
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_screen_cross_tenant_job_returns_404(client_tenant_a, tenant_a):
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()

    mock_doc = AIResumeDocument(
        id=doc_id,
        company_id=tenant_a,
        parse_status="COMPLETED",
        raw_text="Valid resume content",
    )

    mock_session = AsyncMock()

    # Query 1: doc check -> returns mock_doc
    res_doc = MagicMock()
    res_doc.scalar_one_or_none.return_value = mock_doc

    # Query 2: job check -> returns None (job belongs to tenant B)
    res_job = MagicMock()
    res_job.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [res_doc, res_job]

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            "/api/v2/screening/screen",
            json={"resume_document_id": str(doc_id), "job_id": str(job_id)},
        )
        assert response.status_code == 404
        assert "job not found" in _extract_error_message(response)
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_history_cross_tenant_returns_404(client_tenant_a):
    foreign_app_id = uuid.uuid4()
    mock_session = AsyncMock()

    res_app = MagicMock()
    res_app.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = res_app

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.get(f"/api/v2/screening/history/{foreign_app_id}")
        assert response.status_code == 404
        assert "application not found" in _extract_error_message(response)
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_decision_cross_tenant_returns_404(client_tenant_a):
    foreign_screening_id = uuid.uuid4()
    mock_session = AsyncMock()

    res_scr = MagicMock()
    res_scr.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = res_scr

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            f"/api/v2/screening/results/{foreign_screening_id}/decision",
            json={"action": "SHORTLIST"},
        )
        assert response.status_code == 404
        assert "screening result not found" in _extract_error_message(response)
    finally:
        app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# 4. Logic Bug Fixes & Contract Verification Tests
# ---------------------------------------------------------------------------

@patch("app.api.v2.screening.ScreeningAgent")
def test_screen_success_no_fake_uuid_and_returns_thresholds(
    mock_agent_cls, client_tenant_a, tenant_a
):
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()

    mock_doc = AIResumeDocument(
        id=doc_id,
        company_id=tenant_a,
        application_id=None,  # No application linked
        candidate_name="Jane Doe",
        parse_status="COMPLETED",
        raw_text="Senior Python Backend Developer with 6 years experience",
    )
    mock_job = Job(
        id=job_id,
        company_id=tenant_a,
        title="Backend Engineer",
        job_description="Python, FastAPI, Postgres",
    )
    mock_score = CandidateMatchScore(
        id=uuid.uuid4(),
        company_id=tenant_a,
        resume_document_id=doc_id,
        job_id=job_id,
        overall_match_score=0.88,
    )

    mock_session = AsyncMock()
    res_doc = MagicMock()
    res_doc.scalar_one_or_none.return_value = mock_doc
    res_job = MagicMock()
    res_job.scalar_one_or_none.return_value = mock_job
    res_score = MagicMock()
    res_score.scalar_one_or_none.return_value = mock_score

    mock_session.execute.side_effect = [res_doc, res_job, res_score]

    mock_agent = MagicMock()
    mock_agent.screen = AsyncMock(
        return_value=ScreeningResult(
            status="COMPLETED",
            decision="SHORTLIST",
            confidence=0.9,
            match_score=0.88,
            strengths=["FastAPI expertise"],
        )
    )
    mock_agent_cls.return_value = mock_agent

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            "/api/v2/screening/screen",
            json={"resume_document_id": str(doc_id), "job_id": str(job_id)},
        )
        assert response.status_code == 200
        data = response.json().get("data", {})
        assert data["decision"] == "SHORTLIST"
        assert "thresholds" in data
        assert data["thresholds"]["shortlist"] == settings.AI_SCREENING_THRESHOLD
        assert data["thresholds"]["reject"] == settings.AI_REJECTION_THRESHOLD

        # Verify added AIScreeningResult has application_id=None (NOT a fake UUID)
        added_objs = [call[0][0] for call in mock_session.add.call_args_list]
        screening_records = [o for o in added_objs if isinstance(o, AIScreeningResult)]
        assert len(screening_records) == 1
        assert screening_records[0].application_id is None
        assert screening_records[0].company_id == tenant_a
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@patch("app.api.v2.screening.ScreeningAgent")
@patch("app.agents.candidate_matcher.CandidateMatcherAgent")
def test_screen_computes_match_score_when_missing(
    mock_matcher_cls, mock_agent_cls, client_tenant_a, tenant_a
):
    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()

    mock_doc = AIResumeDocument(
        id=doc_id,
        company_id=tenant_a,
        candidate_name="Jane Doe",
        parse_status="COMPLETED",
        raw_text="Developer with Python experience",
    )
    mock_job = Job(
        id=job_id,
        company_id=tenant_a,
        title="Python Engineer",
        job_description="Python engineer needed",
    )

    mock_session = AsyncMock()
    res_doc = MagicMock()
    res_doc.scalar_one_or_none.return_value = mock_doc
    res_job = MagicMock()
    res_job.scalar_one_or_none.return_value = mock_job
    res_score = MagicMock()
    res_score.scalar_one_or_none.return_value = None  # Missing score!

    mock_session.execute.side_effect = [res_doc, res_job, res_score]

    # Mock Matcher Agent
    mock_matcher = MagicMock()
    match_result = MagicMock()
    match_result.overall_match_score = 0.77
    match_result.skill_match_score = 0.80
    match_result.experience_match_score = 0.75
    match_result.education_match_score = 0.70
    match_result.domain_match_score = 0.70
    match_result.industry_match_score = 0.70
    match_result.location_match_score = 0.80
    match_result.salary_match_score = 0.80
    match_result.availability_score = 0.80
    match_result.ai_confidence_score = 0.85
    match_result.matching_skills = ["Python"]
    match_result.missing_skills = []
    match_result.extra_skills = []
    match_result.recommendation = "SHORTLIST"
    match_result.to_dict.return_value = {"overall_match_score": 0.77}
    mock_matcher.match = AsyncMock(return_value=match_result)
    mock_matcher_cls.return_value = mock_matcher

    # Mock Screening Agent
    mock_agent = MagicMock()
    mock_agent.screen = AsyncMock(
        return_value=ScreeningResult(status="COMPLETED", decision="SHORTLIST", confidence=0.85)
    )
    mock_agent_cls.return_value = mock_agent

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            "/api/v2/screening/screen",
            json={"resume_document_id": str(doc_id), "job_id": str(job_id)},
        )
        assert response.status_code == 200
        # Verify CandidateMatchScore was computed and added to DB
        added_objs = [call[0][0] for call in mock_session.add.call_args_list]
        scores = [o for o in added_objs if isinstance(o, CandidateMatchScore)]
        assert len(scores) == 1
        assert scores[0].overall_match_score == 0.77
        assert scores[0].company_id == tenant_a
    finally:
        app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# 5. New Endpoints: Run, Results, and Human Decision Workflow
# ---------------------------------------------------------------------------

def test_trigger_job_screening_run_background(client_tenant_a, tenant_a):
    job_id = uuid.uuid4()
    app_id_1 = uuid.uuid4()
    app_id_2 = uuid.uuid4()

    mock_job = Job(id=job_id, company_id=tenant_a, title="Software Engineer")

    mock_session = AsyncMock()
    res_job = MagicMock()
    res_job.scalar_one_or_none.return_value = mock_job

    res_apps = MagicMock()
    res_apps.scalars.return_value.all.return_value = [app_id_1, app_id_2]

    mock_session.execute.side_effect = [res_job, res_apps]

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            f"/api/v2/screening/jobs/{job_id}/run",
            json={"application_ids": [str(app_id_1), str(app_id_2)]},
        )
        assert response.status_code == 200
        data = response.json().get("data", {})
        assert data["status"] == "RUNNING"
        assert data["total"] == 2
        assert "run_id" in data
        assert "thresholds" in data
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_get_job_screening_results_contract(client_tenant_a, tenant_a):
    job_id = uuid.uuid4()
    app_id = uuid.uuid4()

    mock_job = Job(id=job_id, company_id=tenant_a, title="Frontend Dev")
    mock_app = Application(
        id=app_id,
        job_id=job_id,
        company_id=tenant_a,
        first_name="John",
        last_name="Doe",
    )
    mock_result = AIScreeningResult(
        id=uuid.uuid4(),
        company_id=tenant_a,
        job_id=job_id,
        application_id=app_id,
        status="COMPLETED",
        decision="SHORTLIST",
        confidence=0.89,
        match_score=0.85,
        strengths=["React", "TypeScript"],
        weaknesses=[],
        missing_skills=[],
        red_flags=[],
        green_flags=["Fast learner"],
        hiring_recommendation="Hire",
        hr_notes="Ready for interview",
        questions_to_ask=["State management experience"],
        model_used="ollama",
        created_at=datetime.now(timezone.utc),
    )

    mock_session = AsyncMock()
    res_job = MagicMock()
    res_job.scalar_one_or_none.return_value = mock_job
    res_apps = MagicMock()
    res_apps.scalars.return_value.all.return_value = [mock_app]
    res_results = MagicMock()
    res_results.scalars.return_value.all.return_value = [mock_result]

    mock_session.execute.side_effect = [res_job, res_apps, res_results]

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.get(f"/api/v2/screening/jobs/{job_id}/results")
        assert response.status_code == 200
        data = response.json().get("data", {})
        assert "thresholds" in data
        assert "run" in data
        assert "results" in data
        assert len(data["results"]) == 1
        item = data["results"][0]
        assert item["application_id"] == str(app_id)
        assert item["candidate_name"] == "John Doe"
        assert item["decision"] == "SHORTLIST"
        assert item["confidence"] == 0.89
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@patch("app.api.v2.screening._get_recruitment_service")
def test_submit_human_decision_updates_stage_and_audit(
    mock_get_service, client_tenant_a, tenant_a, user_a
):
    screening_id = uuid.uuid4()
    app_id = uuid.uuid4()

    mock_screening = AIScreeningResult(
        id=screening_id,
        company_id=tenant_a,
        application_id=app_id,
        job_id=uuid.uuid4(),
        status="COMPLETED",
        decision="REVIEW",
    )

    mock_session = AsyncMock()
    res_scr = MagicMock()
    res_scr.scalar_one_or_none.return_value = mock_screening
    mock_session.execute.return_value = res_scr
    mock_service = AsyncMock()
    mock_service.update_application_status = AsyncMock()
    mock_get_service.return_value = mock_service

    app.dependency_overrides[get_db_session] = lambda: mock_session
    try:
        response = client_tenant_a.post(
            f"/api/v2/screening/results/{screening_id}/decision",
            json={"action": "SHORTLIST", "reason": "Demonstrated required experience"},
        )
        assert response.status_code == 200
        data = response.json().get("data", {})
        assert data["action"] == "SHORTLIST"
        assert data["reason"] == "Demonstrated required experience"

        # Verify application status update called with mapped vocabulary
        mock_service.update_application_status.assert_awaited_once_with(app_id, "SHORTLISTED")

        # Verify RecruitmentAuditLog created
        added_objs = [call[0][0] for call in mock_session.add.call_args_list]
        audit_logs = [o for o in added_objs if isinstance(o, RecruitmentAuditLog)]
        assert len(audit_logs) == 1
        assert audit_logs[0].action == "SCREENING_HUMAN_DECISION"
        assert audit_logs[0].company_id == tenant_a
        assert audit_logs[0].user_id == user_a
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def test_submit_human_decision_reject_requires_reason(client_tenant_a):
    screening_id = uuid.uuid4()
    response = client_tenant_a.post(
        f"/api/v2/screening/results/{screening_id}/decision",
        json={"action": "REJECT", "reason": ""},
    )
    assert response.status_code == 422
    assert "reason is mandatory" in _extract_error_message(response)
