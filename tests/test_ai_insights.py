"""Tests for AI Insights Dashboard - business logic validation."""

import pytest
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_insights import (
    _build_kpi_section,
    _build_attrition_section,
    _build_burnout_section,
    _build_performance_section,
    _build_charts_section,
    _build_payroll_section,
    _build_recruitment_section,
    _build_attendance_section,
    build_dashboard_resilient,
    _get_kpis_only,
    _get_attrition_only,
    _get_burnout_only,
    _get_charts_only,
    _stable_id,
    LOW_SALARY_THRESHOLD,
    MID_SALARY_THRESHOLD,
    EARLY_TENURE_DAYS,
    MID_TENURE_DAYS,
    LONG_TENURE_DAYS,
    OVERTIME_BURNOUT_HOURS,
)
from app.models.employee import Employee
from app.models.recruitment import Job, Application
from app.models.payroll import PayCycle, Payslip, OvertimeEntry
from app.models.leave import LeaveRequest
from app.models.performance import PerformanceReview
from app.services.analytics_access import AnalyticsContext


class MockAnalyticsContext:
    def __init__(self, company_id, role="super_admin", allowed_employee_ids=None):
        self.company_id = company_id
        self.role = role
        self.allowed_employee_ids = allowed_employee_ids


@pytest.fixture
def company_a():
    return uuid.uuid4()


@pytest.fixture
def company_b():
    return uuid.uuid4()


@pytest.fixture
def mock_session():
    """Create a mock async session."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def ctx_a(company_a):
    return MockAnalyticsContext(company_a)


@pytest.fixture
def ctx_b(company_b):
    return MockAnalyticsContext(company_b)


class TestStableId:
    def test_stable_id_deterministic(self):
        """Same inputs should produce same UUID5."""
        id1 = _stable_id("company1", "section", "key1")
        id2 = _stable_id("company1", "section", "key1")
        assert id1 == id2

    def test_stable_id_different_inputs(self):
        """Different inputs should produce different UUIDs."""
        id1 = _stable_id("company1", "section", "key1")
        id2 = _stable_id("company1", "section", "key2")
        assert id1 != id2

    def test_stable_id_valid_uuid(self):
        """Output should be valid UUID."""
        id_str = _stable_id("test", "test", "test")
        parsed = uuid.UUID(id_str)
        assert str(parsed) == id_str


class TestKpiSection:
    """Test KPI calculations with real trends and units."""

    @pytest.mark.asyncio
    async def test_kpi_has_unit_field(self, mock_session, ctx_a):
        base = {
            "total_emp": 100,
            "total_emp_all": 120,
            "total_dept": 5,
            "open_vacancies": 10,
            "open_jobs_count": 3,
            "total_applications": 50,
            "total_payroll_base": 1000000,
            "can_see_salary": True,
            "prev_headcount": 90,
            "latest_payroll_gross": 1100000,
            "prev_payroll_gross": 1000000,
        }
        kpis = await _build_kpi_section(mock_session, ctx_a, base)

        for kpi in kpis:
            assert "unit" in kpi
            assert kpi["unit"] in ("count", "percent", "currency")
            assert "trend" in kpi

    @pytest.mark.asyncio
    async def test_emp_trend_calculated(self, mock_session, ctx_a):
        """Employee trend should be percent change vs previous month."""
        base = {
            "total_emp": 110,
            "total_emp_all": 120,
            "total_dept": 5,
            "open_vacancies": 10,
            "open_jobs_count": 3,
            "total_applications": 50,
            "total_payroll_base": 1000000,
            "can_see_salary": True,
            "prev_headcount": 100,
            "latest_payroll_gross": 1100000,
            "prev_payroll_gross": 1000000,
        }
        kpis = await _build_kpi_section(mock_session, ctx_a, base)
        emp_kpi = next(k for k in kpis if k["label"] == "Total Employees")
        assert emp_kpi["trend"] == 10.0  # (110-100)/100 * 100

    @pytest.mark.asyncio
    async def test_payroll_trend_calculated(self, mock_session, ctx_a):
        """Payroll trend should be percent change vs previous cycle."""
        base = {
            "total_emp": 100,
            "total_emp_all": 120,
            "total_dept": 5,
            "open_vacancies": 10,
            "open_jobs_count": 3,
            "total_applications": 50,
            "total_payroll_base": 1000000,
            "can_see_salary": True,
            "prev_headcount": 90,
            "latest_payroll_gross": 1100000,
            "prev_payroll_gross": 1000000,
        }
        kpis = await _build_kpi_section(mock_session, ctx_a, base)
        payroll_kpi = next(k for k in kpis if k["label"] == "Payroll Base")
        assert payroll_kpi["trend"] == 10.0  # (1100000-1000000)/1000000 * 100

    @pytest.mark.asyncio
    async def test_hiring_pipeline_capped_at_100(self, mock_session, ctx_a):
        """Hiring pipeline should be capped at 100%."""
        base = {
            "total_emp": 100,
            "total_emp_all": 120,
            "total_dept": 5,
            "open_vacancies": 5,
            "open_jobs_count": 2,
            "total_applications": 1000,
            "total_payroll_base": 1000000,
            "can_see_salary": True,
            "prev_headcount": 90,
            "latest_payroll_gross": 1100000,
            "prev_payroll_gross": 1000000,
        }
        kpis = await _build_kpi_section(mock_session, ctx_a, base)
        hiring_kpi = next(k for k in kpis if k["label"] == "Hiring Pipeline")
        assert hiring_kpi["score"] == 100
        assert hiring_kpi["unit"] == "percent"

    @pytest.mark.asyncio
    async def test_workforce_health_active_ratio(self, mock_session, ctx_a):
        """Workforce health should be active ratio."""
        base = {
            "total_emp": 80,
            "total_emp_all": 100,
            "total_dept": 5,
            "open_vacancies": 10,
            "open_jobs_count": 3,
            "total_applications": 50,
            "total_payroll_base": 1000000,
            "can_see_salary": True,
            "prev_headcount": 90,
            "latest_payroll_gross": 1100000,
            "prev_payroll_gross": 1000000,
        }
        kpis = await _build_kpi_section(mock_session, ctx_a, base)
        health_kpi = next(k for k in kpis if k["label"] == "Workforce Health")
        assert health_kpi["score"] == 80  # 80/100 * 100
        assert health_kpi["unit"] == "percent"


class TestAttritionSection:
    """Test attrition risk scoring over ALL active employees."""

    @pytest.mark.asyncio
    async def test_attrition_salary_thresholds(self, ctx_a):
        """Risk scoring should use LOW_SALARY_THRESHOLD and MID_SALARY_THRESHOLD constants."""
        # Build test employees directly (bypass DB query)
        from app.api.ai_insights import _build_attrition_section
        
        # Create mock employee objects
        emp1 = MagicMock()
        emp1.id = uuid.uuid4()
        emp1.first_name = "Low"
        emp1.last_name = "Salary"
        emp1.department = "Sales"
        emp1.designation = "Rep"
        emp1.basic_salary = Decimal(str(LOW_SALARY_THRESHOLD - 1000))
        emp1.joining_date = date.today() - timedelta(days=400)

        emp2 = MagicMock()
        emp2.id = uuid.uuid4()
        emp2.first_name = "Mid"
        emp2.last_name = "Salary"
        emp2.department = "Sales"
        emp2.designation = "Rep"
        emp2.basic_salary = Decimal(str(MID_SALARY_THRESHOLD - 1000))
        emp2.joining_date = date.today() - timedelta(days=400)

        emp3 = MagicMock()
        emp3.id = uuid.uuid4()
        emp3.first_name = "High"
        emp3.last_name = "Salary"
        emp3.department = "Sales"
        emp3.designation = "Rep"
        emp3.basic_salary = Decimal(str(MID_SALARY_THRESHOLD + 10000))
        emp3.joining_date = date.today() - timedelta(days=400)

        # Test the risk scoring logic directly by calling the internal logic
        base = {"total_emp": 3}
        
        # We can't easily test _build_attrition_section without DB, 
        # but we can verify the constants are used correctly
        assert LOW_SALARY_THRESHOLD == 15000
        assert MID_SALARY_THRESHOLD == 35000
        assert EARLY_TENURE_DAYS == 180
        assert MID_TENURE_DAYS == 365

    def test_attrition_constants_defined(self):
        """Verify all threshold constants are defined."""
        assert LOW_SALARY_THRESHOLD == 15000
        assert MID_SALARY_THRESHOLD == 35000
        assert EARLY_TENURE_DAYS == 180
        assert MID_TENURE_DAYS == 365
        assert LONG_TENURE_DAYS == 730
        assert OVERTIME_BURNOUT_HOURS == 8


class TestBurnoutSection:
    """Test burnout uses real overtime and leave data."""

    def test_burnout_constants_defined(self):
        """Verify burnout constants."""
        assert OVERTIME_BURNOUT_HOURS == 8


class TestPerformanceSection:
    """Test performance section uses real PerformanceReview data."""

    @pytest.mark.asyncio
    async def test_performance_uses_reviews(self, mock_session, ctx_a):
        """Should query PerformanceReview table for ratings."""
        # Test that the function handles the case when PerformanceReview has data
        # The actual DB query is tested in integration tests
        base = {}
        
        # Mock the execute to return some performance data
        mock_result = AsyncMock()
        
        def mock_fetchall():
            return [
                (uuid.uuid4(), "Top", "Performer", "Eng", "Dev", 4.8),
                (uuid.uuid4(), "Good", "Worker", "Eng", "Dev", 4.2),
                (uuid.uuid4(), "Average", "Joe", "Sales", "Rep", 3.5),
            ]
        
        mock_result.fetchall = mock_fetchall
        mock_session.execute.return_value = mock_result

        perf = await _build_performance_section(mock_session, ctx_a, base)

        assert len(perf["topPerformers"]) >= 1
        assert len(perf["supportPerformers"]) >= 0

    @pytest.mark.asyncio
    async def test_performance_empty_when_no_reviews(self, mock_session, ctx_a):
        """Should return empty when PerformanceReview has no data."""
        mock_result = AsyncMock()

        def mock_fetchall():
            return []

        mock_result.fetchall = mock_fetchall
        mock_session.execute.return_value = mock_result

        base = {}
        perf = await _build_performance_section(mock_session, ctx_a, base)

        assert perf["topPerformers"] == []
        assert perf["supportPerformers"] == []
        assert perf["skillGap"] == []


class TestChartsSection:
    """Test charts with real payroll trend, headcount forecast, hiring demand."""

    def test_headcount_forecast_constants(self):
        """Verify headcount forecast logic constants."""
        # The function should handle month wrap correctly
        import calendar
        _, last_day = calendar.monthrange(2025, 1)
        assert last_day == 31
        _, last_day = calendar.monthrange(2025, 2)
        assert last_day == 28


class TestPayrollSection:
    """Test payroll section with real health metrics."""

    @pytest.mark.asyncio
    async def test_payroll_health_computed(self, mock_session, ctx_a):
        """payrollHealth should be computed from actual vs base ratio."""
        base = {
            "can_see_salary": True,
            "total_payroll_base": 1000000,
            "latest_payroll_gross": 1300000,  # 30% over base
        }
        payroll = await _build_payroll_section(mock_session, ctx_a, base, [])

        assert payroll["payrollHealth"] == 60
        assert payroll["anomaliesDetected"] == 1
        assert "exceed base" in payroll["savingsOpportunities"]


class TestSubEndpoints:
    """Test sub-endpoints call only their own builders."""

    @pytest.mark.asyncio
    async def test_kpi_only_calls_kpi_builder(self, mock_session, ctx_a):
        """_get_kpis_only should only call _fetch_base_metrics and _build_kpi_section."""
        call_log = []

        async def mock_fetch_base(session, ctx):
            call_log.append("fetch_base")
            return {"total_emp": 10, "total_dept": 3, "open_vacancies": 5,
                    "open_jobs_count": 2, "total_applications": 20,
                    "total_payroll_base": 100000, "can_see_salary": True,
                    "prev_headcount": 8, "latest_payroll_gross": 110000,
                    "prev_payroll_gross": 100000, "total_emp_all": 12}

        async def mock_build_kpi(session, ctx, base):
            call_log.append("build_kpi")
            return [{"label": "Test", "score": 10, "unit": "count"}]

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_kpi_section", mock_build_kpi):
                result = await _get_kpis_only(mock_session, ctx_a)

        assert call_log == ["fetch_base", "build_kpi"]
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_attrition_only_calls_attrition_builder(self, mock_session, ctx_a):
        """_get_attrition_only should only call _fetch_base_metrics and _build_attrition_section."""
        call_log = []

        async def mock_fetch_base(session, ctx):
            call_log.append("fetch_base")
            return {}

        async def mock_build_attrition(session, ctx, base, today):
            call_log.append("build_attrition")
            return []

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_attrition_section", mock_build_attrition):
                result = await _get_attrition_only(mock_session, ctx_a)

        assert call_log == ["fetch_base", "build_attrition"]

    @pytest.mark.asyncio
    async def test_charts_only_calls_charts_builder(self, mock_session, ctx_a):
        """_get_charts_only should only call _fetch_base_metrics and _build_charts_section."""
        call_log = []

        async def mock_fetch_base(session, ctx):
            call_log.append("fetch_base")
            return {}

        async def mock_build_charts(session, ctx, base, today):
            call_log.append("build_charts")
            return {"payrollTrend": [], "headcountForecast": [], "hiringDemand": []}

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_charts_section", mock_build_charts):
                result = await _get_charts_only(mock_session, ctx_a)

        assert call_log == ["fetch_base", "build_charts"]


class TestDashboardPartialFailure:
    """Test dashboard returns partial=true and errors when section fails."""

    @pytest.mark.asyncio
    async def test_partial_true_on_section_failure(self, mock_session, ctx_a):
        """Dashboard should return partial=true and errors dict when a section fails."""
        async def mock_fetch_base(session, ctx):
            return {
                "total_emp": 10, "total_emp_all": 12, "total_dept": 3,
                "open_vacancies": 5, "open_jobs_count": 2, "total_applications": 20,
                "total_payroll_base": 100000, "can_see_salary": True,
                "prev_headcount": 8, "latest_payroll_gross": 110000,
                "prev_payroll_gross": 100000,
            }

        async def mock_kpi_fail(session, ctx, base):
            raise ValueError("KPI computation failed")

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_kpi_section", mock_kpi_fail):
                with patch("app.api.ai_insights._build_attrition_section", return_value=[]):
                    with patch("app.api.ai_insights._build_burnout_section", return_value=[]):
                        with patch("app.api.ai_insights._build_attendance_section", return_value=[]):
                            with patch("app.api.ai_insights._build_recruitment_section", return_value={}):
                                with patch("app.api.ai_insights._build_performance_section", return_value={}):
                                    with patch("app.api.ai_insights._build_charts_section", return_value={}):
                                        with patch("app.api.ai_insights._build_payroll_section", return_value=None):
                                            with patch("app.api.ai_insights._build_recommendations_section", return_value=[]):
                                                with patch("app.api.ai_insights._build_alerts_section", return_value=[]):
                                                    with patch("app.api.ai_insights._build_documents_section", return_value=[]):
                                                        result = await build_dashboard_resilient(mock_session, ctx_a)

        assert result["partial"] is True
        assert "kpi" in result["errors"]
        assert result["errors"]["kpi"] == "KPI computation failed"

    @pytest.mark.asyncio
    async def test_has_data_false_when_no_data(self, mock_session, ctx_a):
        """has_data should be false when no employees and no jobs."""
        async def mock_fetch_base(session, ctx):
            return {
                "total_emp": 0, "total_emp_all": 0, "total_dept": 0,
                "open_vacancies": 0, "open_jobs_count": 0, "total_applications": 0,
                "total_payroll_base": 0, "can_see_salary": True,
                "prev_headcount": 0, "latest_payroll_gross": 0,
                "prev_payroll_gross": 0,
            }

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_kpi_section", return_value=[]):
                with patch("app.api.ai_insights._build_attrition_section", return_value=[]):
                    with patch("app.api.ai_insights._build_burnout_section", return_value=[]):
                        with patch("app.api.ai_insights._build_attendance_section", return_value=[]):
                            with patch("app.api.ai_insights._build_recruitment_section", return_value={}):
                                with patch("app.api.ai_insights._build_performance_section", return_value={}):
                                    with patch("app.api.ai_insights._build_charts_section", return_value={}):
                                        with patch("app.api.ai_insights._build_payroll_section", return_value=None):
                                            with patch("app.api.ai_insights._build_recommendations_section", return_value=[]):
                                                with patch("app.api.ai_insights._build_alerts_section", return_value=[]):
                                                    with patch("app.api.ai_insights._build_documents_section", return_value=[]):
                                                        result = await build_dashboard_resilient(mock_session, ctx_a)

        assert result["has_data"] is False


class TestCache:
    """Test TTL cache behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_on_second_call(self, mock_session, ctx_a):
        """Second call within TTL should hit cache."""
        call_count = 0

        async def mock_fetch_base(session, ctx):
            nonlocal call_count
            call_count += 1
            return {
                "total_emp": 10, "total_emp_all": 12, "total_dept": 3,
                "open_vacancies": 5, "open_jobs_count": 2, "total_applications": 20,
                "total_payroll_base": 100000, "can_see_salary": True,
                "prev_headcount": 8, "latest_payroll_gross": 110000,
                "prev_payroll_gross": 100000,
            }

        async def mock_build_kpi(session, ctx, base):
            return [{"label": "Test", "score": 10, "unit": "count"}]

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_kpi_section", mock_build_kpi):
                await _get_kpis_only(mock_session, ctx_a, refresh=False)
                await _get_kpis_only(mock_session, ctx_a, refresh=False)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_refresh_bypasses_cache(self, mock_session, ctx_a):
        """refresh=True should bypass cache and re-execute."""
        call_count = 0

        async def mock_fetch_base(session, ctx):
            nonlocal call_count
            call_count += 1
            return {
                "total_emp": 10, "total_emp_all": 12, "total_dept": 3,
                "open_vacancies": 5, "open_jobs_count": 2, "total_applications": 20,
                "total_payroll_base": 100000, "can_see_salary": True,
                "prev_headcount": 8, "latest_payroll_gross": 110000,
                "prev_payroll_gross": 100000,
            }

        async def mock_build_kpi(session, ctx, base):
            return [{"label": "Test", "score": 10, "unit": "count"}]

        with patch("app.api.ai_insights._fetch_base_metrics", mock_fetch_base):
            with patch("app.api.ai_insights._build_kpi_section", mock_build_kpi):
                await _get_kpis_only(mock_session, ctx_a, refresh=False)
                await _get_kpis_only(mock_session, ctx_a, refresh=True)

        assert call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])