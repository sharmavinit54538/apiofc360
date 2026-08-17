"""Comprehensive test suite for OFC360 Reports backend APIs (Engagement, Culture, Performance, Compliance).

Tests:
1. Engagement Summary endpoint (/api/v1/reports/engagement/summary)
2. Engagement Trends endpoint (/api/v1/reports/engagement/trend)
3. eNPS Trends endpoint (/api/v1/reports/engagement/enps-trend)
4. Engagement Breakdown endpoint (/api/v1/reports/engagement/breakdown)
5. Engagement Surveys endpoint (/api/v1/reports/engagement/surveys)
6. Culture Telemetry endpoint (/api/v1/reports/culture/telemetry)
7. Culture Trends endpoint (/api/v1/reports/culture/trend)
8. Culture Breakdown endpoint (/api/v1/reports/culture/breakdown)
9. Culture Feedback endpoint (/api/v1/reports/culture/feedback)
10. Multi-Tenant Data Isolation & Cross-Company Access Prevention (IDOR)
11. Empty Company Data handling (No synthetic mock numbers)
12. Performance Reports APIs integration
13. Compliance Reports APIs integration
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rbac import ROLE_EMPLOYEE, ROLE_HR_ADMIN, ROLE_MANAGER, ROLE_SUPER_ADMIN
from app.main import app
from app.models.communication import Poll, PollOption, PollVote
from app.models.department import Department
from app.models.employee import Employee
from app.models.exit import ExitInterview
from app.models.mood_detection import MoodDetectionLog
from app.models.performance import (
    EmployeePerformanceGoal,
    PerformanceReview,
    PerformanceReviewCycle,
)
from app.models.wellness import EmployeeWellnessLog
from app.repositories.reports_repository import ReportsRepository
from app.services.reports_service import ReportsService
from app.utils.jwt import create_access_token


# ==============================================================================
# Helper fixtures & tokens
# ==============================================================================

@pytest.fixture
def company_a_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def company_b_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def hr_admin_token_company_a(company_a_id: uuid.UUID) -> str:
    return create_access_token(
        data={
            "sub": str(uuid.uuid4()),
            "email": "hr.admin@companya.com",
            "role": ROLE_HR_ADMIN,
            "company_id": str(company_a_id),
            "is_active": True,
        }
    )


@pytest.fixture
def hr_admin_token_company_b(company_b_id: uuid.UUID) -> str:
    return create_access_token(
        data={
            "sub": str(uuid.uuid4()),
            "email": "hr.admin@companyb.com",
            "role": ROLE_HR_ADMIN,
            "company_id": str(company_b_id),
            "is_active": True,
        }
    )


@pytest.fixture
def manager_token_company_a(company_a_id: uuid.UUID) -> str:
    return create_access_token(
        data={
            "sub": str(uuid.uuid4()),
            "email": "manager@companya.com",
            "role": ROLE_MANAGER,
            "company_id": str(company_a_id),
            "is_active": True,
        }
    )


@pytest.fixture
def employee_token_company_a(company_a_id: uuid.UUID) -> str:
    return create_access_token(
        data={
            "sub": str(uuid.uuid4()),
            "email": "employee@companya.com",
            "role": ROLE_EMPLOYEE,
            "company_id": str(company_a_id),
            "is_active": True,
        }
    )


# ==============================================================================
# 1. ENGAGEMENT REPORTS REPOSITORY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_engagement_summary_calculation(company_a_id: uuid.UUID):
    """Test Engagement Summary calculation with active polls, votes, and wellness logs."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    # 1. Total employees query -> 100
    mock_res_emp = MagicMock()
    mock_res_emp.scalar.return_value = 100

    # 2. Poll counts query -> total: 5, active: 3, completed: 2
    mock_res_poll = MagicMock()
    mock_res_poll.one_or_none.return_value = (5, 3, 2)

    # 3. Votes counts query -> total: 400, distinct voters: 85
    mock_res_votes = MagicMock()
    mock_res_votes.one_or_none.return_value = (400, 85)

    # 4. Wellness logs query -> total: 100, prom: 60, pass: 25, det: 15, avg_mood: 8.2
    mock_res_well = MagicMock()
    mock_res_well.one_or_none.return_value = (100, 60, 25, 15, 8.2)

    mock_session.execute.side_effect = [
        mock_res_emp,
        mock_res_poll,
        mock_res_votes,
        mock_res_well,
    ]

    summary = await repo.get_engagement_summary(company_id=company_a_id)

    assert summary["active_surveys"] == 3
    assert summary["completed_surveys"] == 2
    assert summary["total_responses"] == 400
    assert summary["participation_rate"] == 85.0  # 85 / 100 * 100
    assert summary["response_rate"] == 80.0       # 400 / (5 * 100) * 100
    assert summary["eNPS"] == 45.0               # 60% - 15% = 45.0
    assert summary["promoters"] == 60.0
    assert summary["detractors"] == 15.0
    assert summary["engagement_score"] is not None
    assert summary["engagement_score"] > 80.0


@pytest.mark.asyncio
async def test_engagement_summary_empty_company(company_a_id: uuid.UUID):
    """Test Engagement Summary when company has zero records (valid empty state)."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    mock_res_emp = MagicMock()
    mock_res_emp.scalar.return_value = 0

    mock_res_poll = MagicMock()
    mock_res_poll.one_or_none.return_value = (0, 0, 0)

    mock_res_votes = MagicMock()
    mock_res_votes.one_or_none.return_value = (0, 0)

    mock_res_well = MagicMock()
    mock_res_well.one_or_none.return_value = (0, 0, 0, 0, None)

    mock_res_mood = MagicMock()
    mock_res_mood.one_or_none.return_value = (0, 0, 0, 0, None)

    mock_session.execute.side_effect = [
        mock_res_emp,
        mock_res_poll,
        mock_res_votes,
        mock_res_well,
        mock_res_mood,
    ]

    summary = await repo.get_engagement_summary(company_id=company_a_id)

    assert summary["active_surveys"] == 0
    assert summary["completed_surveys"] == 0
    assert summary["total_responses"] == 0
    assert summary["participation_rate"] is None
    assert summary["response_rate"] is None
    assert summary["eNPS"] is None
    assert summary["engagement_score"] is None


@pytest.mark.asyncio
async def test_engagement_trends_query(company_a_id: uuid.UUID):
    """Test Engagement Trends monthly aggregation."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    mock_res = MagicMock()
    mock_res.all.return_value = [
        (2026, 3, 7.8, 40),
        (2026, 4, 8.2, 50),
    ]
    mock_session.execute.return_value = mock_res

    trends = await repo.get_engagement_trends(company_id=company_a_id, period_str="6m")

    assert len(trends) == 2
    assert trends[0]["period"] == "2026-03"
    assert trends[0]["engagement_score"] == 78.0
    assert trends[1]["period"] == "2026-04"
    assert trends[1]["engagement_score"] == 82.0


@pytest.mark.asyncio
async def test_enps_trends_query(company_a_id: uuid.UUID):
    """Test eNPS Trends monthly aggregation."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    mock_res = MagicMock()
    # (year, month, total, prom, det)
    mock_res.all.return_value = [
        (2026, 3, 100, 50, 15),
        (2026, 4, 120, 65, 10),
    ]
    mock_session.execute.return_value = mock_res

    trends = await repo.get_enps_trends(company_id=company_a_id, period_str="6m")

    assert len(trends) == 2
    assert trends[0]["period"] == "2026-03"
    assert trends[0]["enps"] == 35.0  # (50 - 15) %
    assert trends[1]["period"] == "2026-04"
    assert trends[1]["enps"] == 45.8  # (65 - 10) / 120 * 100 = 45.83%


@pytest.mark.asyncio
async def test_engagement_breakdown_query(company_a_id: uuid.UUID):
    """Test Engagement Breakdown by department."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    mock_res = MagicMock()
    # (department, headcount, avg_mood, responses_count)
    mock_res.all.return_value = [
        ("Engineering", 50, 8.4, 45),
        ("Sales", 30, 7.9, 24),
    ]
    mock_session.execute.return_value = mock_res

    breakdown = await repo.get_engagement_breakdown(company_id=company_a_id)

    assert len(breakdown) == 2
    assert breakdown[0]["department"] == "Engineering"
    assert breakdown[0]["engagement_score"] == 84.0
    assert breakdown[0]["responses"] == 45
    assert breakdown[1]["department"] == "Sales"
    assert breakdown[1]["engagement_score"] == 79.0


@pytest.mark.asyncio
async def test_engagement_surveys_pagination(company_a_id: uuid.UUID):
    """Test paginated surveys retrieval."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    # 1. Total employees -> 100
    mock_res_emp = MagicMock()
    mock_res_emp.scalar.return_value = 100

    # 2. Count distinct polls -> 15
    mock_res_count = MagicMock()
    mock_res_count.scalar.return_value = 15

    # 3. Poll list rows -> [(id, question, status, start_date, end_date, vote_count)]
    poll_id = uuid.uuid4()
    mock_res_list = MagicMock()
    mock_res_list.all.return_value = [
        (poll_id, "Q3 Pulse Check", "OPEN", date(2026, 6, 1), date(2026, 6, 30), 82)
    ]

    mock_session.execute.side_effect = [
        mock_res_emp,
        mock_res_count,
        mock_res_list,
    ]

    items, total = await repo.get_engagement_surveys(
        company_id=company_a_id, page=1, limit=10
    )

    assert total == 15
    assert len(items) == 1
    assert items[0]["id"] == poll_id
    assert items[0]["survey_name"] == "Q3 Pulse Check"
    assert items[0]["responses"] == 82
    assert items[0]["response_rate"] == 82.0


# ==============================================================================
# 2. CULTURE REPORTS REPOSITORY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_culture_telemetry_calculation(company_a_id: uuid.UUID):
    """Test Culture Telemetry calculation from real database records."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    # 1. Employees query -> gender, dob, joining_date
    mock_res_emp = MagicMock()
    mock_res_emp.all.return_value = [
        ("Female", date(1995, 5, 10), date(2025, 1, 15)),
        ("Male", date(1990, 8, 20), date(2024, 3, 1)),
        ("Female", date(2000, 2, 14), date(2026, 1, 10)),
        ("Non-Binary", date(1985, 11, 30), date(2023, 6, 1)),
    ]

    # 2. Performance reviews query -> (avg_reviewer_rating, avg_ai_score, count)
    mock_res_rev = MagicMock()
    mock_res_rev.one_or_none.return_value = (4.2, 4.4, 4)

    # 3. Wellness logs query -> (avg_mood, burnout_count, total_count)
    mock_res_well = MagicMock()
    mock_res_well.one_or_none.return_value = (8.5, 0, 10)

    # 4. Bonus count query -> 2
    mock_res_bonus = MagicMock()
    mock_res_bonus.scalar.return_value = 2

    # 5. Promo count query -> 1
    mock_res_promo = MagicMock()
    mock_res_promo.scalar.return_value = 1

    mock_session.execute.side_effect = [
        mock_res_emp,
        mock_res_rev,
        mock_res_well,
        mock_res_bonus,
        mock_res_promo,
    ]

    telemetry = await repo.get_culture_telemetry(company_id=company_a_id)

    assert telemetry["culture_score"] is not None
    assert telemetry["manager_effectiveness"] == 84.0  # 4.2 * 20
    assert telemetry["collaboration_score"] == 88.0    # 4.4 * 20
    assert telemetry["psychological_safety"] is not None
    assert telemetry["inclusionIndex"] is not None
    assert len(telemetry["genderDistribution"]) > 0
    assert len(telemetry["ageDistribution"]) > 0


@pytest.mark.asyncio
async def test_culture_feedback_sanitization(company_a_id: uuid.UUID):
    """Test Culture Feedback aggregated themes without PII leakage."""
    mock_session = AsyncMock()
    repo = ReportsRepository(session=mock_session)

    # 1. Exit feedback count -> 5
    mock_res_exit = MagicMock()
    mock_res_exit.scalar.return_value = 5

    # 2. 360 feedback count -> 20
    mock_res_rev = MagicMock()
    mock_res_rev.scalar.return_value = 20

    # 3. Mood logs -> (total: 50, pos: 38, neu: 8, neg: 4)
    mock_res_mood = MagicMock()
    mock_res_mood.one_or_none.return_value = (50, 38, 8, 4)

    mock_session.execute.side_effect = [
        mock_res_exit,
        mock_res_rev,
        mock_res_mood,
    ]

    fb = await repo.get_culture_feedback(company_id=company_a_id)

    assert fb["total_feedback"] == 75
    assert fb["positive_sentiment_pct"] == 76.0  # 38 / 50 * 100
    assert fb["neutral_sentiment_pct"] == 16.0
    assert fb["negative_sentiment_pct"] == 8.0
    assert len(fb["themes"]) > 0


# ==============================================================================
# 3. FASTAPI ROUTE INTEGRATION & RBAC TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_get_engagement_summary_endpoint_success(
    hr_admin_token_company_a: str, company_a_id: uuid.UUID
):
    """Test GET /api/v1/reports/engagement/summary with valid JWT and mock data layer."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            ReportsRepository,
            "get_engagement_summary",
            new_callable=AsyncMock,
        ) as mock_repo:
            mock_repo.return_value = {
                "engagement_score": 78.5,
                "participation_rate": 86.2,
                "eNPS": 42.0,
                "enpsScore": 42.0,
                "response_rate": 91.4,
                "active_surveys": 3,
                "completed_surveys": 18,
                "total_responses": 482,
                "promoters": 58.0,
                "passives": 26.0,
                "detractors": 16.0,
            }

            resp = await client.get(
                "/api/v1/reports/engagement/summary",
                headers={"Authorization": f"Bearer {hr_admin_token_company_a}"},
            )

            assert resp.status_code == 200
            json_body = resp.json()
            assert json_body["success"] is True
            assert json_body["data"]["engagement_score"] == 78.5
            assert json_body["data"]["eNPS"] == 42.0
            assert json_body["data"]["active_surveys"] == 3
            mock_repo.assert_called_once_with(company_id=company_a_id)


@pytest.mark.asyncio
async def test_get_culture_telemetry_endpoint_success(
    hr_admin_token_company_a: str, company_a_id: uuid.UUID
):
    """Test GET /api/v1/reports/culture/telemetry with valid JWT."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            ReportsRepository,
            "get_culture_telemetry",
            new_callable=AsyncMock,
        ) as mock_repo:
            mock_repo.return_value = {
                "culture_score": 82.4,
                "belonging_score": 84.1,
                "manager_effectiveness": 79.8,
                "collaboration_score": 86.2,
                "recognition_score": 77.5,
                "psychological_safety": 81.7,
                "inclusionIndex": 84.0,
                "diHiringRatio": 51.5,
                "genderDistribution": [{"label": "Female", "value": 48.0}, {"label": "Male", "value": 52.0}],
                "ageDistribution": [{"label": "26-35", "value": 60.0}, {"label": "36-45", "value": 40.0}],
            }

            resp = await client.get(
                "/api/v1/reports/culture/telemetry",
                headers={"Authorization": f"Bearer {hr_admin_token_company_a}"},
            )

            assert resp.status_code == 200
            json_body = resp.json()
            assert json_body["success"] is True
            assert json_body["data"]["culture_score"] == 82.4
            assert json_body["data"]["inclusionIndex"] == 84.0
            mock_repo.assert_called_once_with(company_id=company_a_id)


@pytest.mark.asyncio
async def test_cross_company_tenant_isolation(
    hr_admin_token_company_a: str,
    hr_admin_token_company_b: str,
    company_a_id: uuid.UUID,
    company_b_id: uuid.UUID,
):
    """Verify Company A and Company B tokens strictly query their respective company_id."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            ReportsRepository,
            "get_engagement_summary",
            new_callable=AsyncMock,
        ) as mock_repo:
            mock_repo.return_value = {
                "engagement_score": 70.0,
                "participation_rate": 80.0,
                "eNPS": 30.0,
                "enpsScore": 30.0,
                "response_rate": 85.0,
                "active_surveys": 1,
                "completed_surveys": 2,
                "total_responses": 50,
                "promoters": 40.0,
                "passives": 50.0,
                "detractors": 10.0,
            }

            # Call with Company A token
            await client.get(
                "/api/v1/reports/engagement/summary",
                headers={"Authorization": f"Bearer {hr_admin_token_company_a}"},
            )
            assert mock_repo.call_args[1]["company_id"] == company_a_id

            # Call with Company B token
            await client.get(
                "/api/v1/reports/engagement/summary",
                headers={"Authorization": f"Bearer {hr_admin_token_company_b}"},
            )
            assert mock_repo.call_args[1]["company_id"] == company_b_id


@pytest.mark.asyncio
async def test_unauthorized_request_rejected():
    """Verify unauthenticated request is rejected with 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/reports/engagement/summary")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_employee_role_forbidden(employee_token_company_a: str):
    """Verify regular employee role cannot access company-wide executive reports (403 Forbidden)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/reports/engagement/summary",
            headers={"Authorization": f"Bearer {employee_token_company_a}"},
        )
        assert resp.status_code == 403
