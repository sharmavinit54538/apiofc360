"""Security tests for Timesheet Management API - Tenant isolation, authorization, review workflow."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from sqlalchemy import select

from app.models.employee import Employee
from app.models.timesheet import Timesheet, TimesheetEntry
from app.models.company import Company
from app.models.user import User
from app.models.user.role import RoleEnum
from app.repositories.timesheet_repository import TimesheetRepository
from app.services.timesheet_service import TimesheetService
from app.core.exceptions import NotFoundException, BadRequestException


class TestTimesheetRepositoryTenantIsolation:
    """Test Timesheet repository tenant isolation."""

    @pytest.mark.asyncio
    async def test_get_timesheet_by_id_requires_company(self):
        """Verify get_timesheet_by_id enforces company_id filter."""
        mock_session = AsyncMock()
        repo = TimesheetRepository(mock_session)

        company_a = uuid.uuid4()
        company_b = uuid.uuid4()
        timesheet_id = uuid.uuid4()
        employee_id = uuid.uuid4()

        mock_timesheet = Timesheet(
            id=timesheet_id,
            employee_id=employee_id,
            week_start_date=date.today(),
            status="PENDING"
        )

        # Company A query
        mock_result_a = MagicMock()
        mock_result_a.scalar_one_or_none.return_value = mock_timesheet
        mock_session.execute.return_value = mock_result_a

        result = await repo.get_timesheet_by_id(timesheet_id, company_a)
        assert result == mock_timesheet

        # Verify query included company_id join filter
        called_stmt = mock_session.execute.call_args[0][0]
        stmt_str = str(called_stmt)
        assert "company_id" in stmt_str

        # Company B query returns None
        mock_result_b = MagicMock()
        mock_result_b.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result_b

        result_b = await repo.get_timesheet_by_id(timesheet_id, company_b)
        assert result_b is None

    @pytest.mark.asyncio
    async def test_get_pending_timesheets_tenant_isolation(self):
        """Verify get_pending_timesheets filters by company_id."""
        mock_session = AsyncMock()
        repo = TimesheetRepository(mock_session)

        company_id = uuid.uuid4()
        mock_timesheets = [
            Timesheet(id=uuid.uuid4(), employee_id=uuid.uuid4(), week_start_date=date.today(), status="PENDING"),
            Timesheet(id=uuid.uuid4(), employee_id=uuid.uuid4(), week_start_date=date.today(), status="PENDING"),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_timesheets
        mock_session.execute.return_value = mock_result

        result = await repo.get_pending_timesheets(company_id=company_id, role="hr_admin")
        assert len(result) == 2

        called_stmt = mock_session.execute.call_args[0][0]
        stmt_str = str(called_stmt)
        assert "company_id" in stmt_str
        # Query uses parameter binding for status, so check for status filter
        assert "status" in stmt_str.lower()

    @pytest.mark.asyncio
    async def test_get_pending_timesheets_manager_filter(self):
        """Verify manager only sees their team's pending timesheets."""
        mock_session = AsyncMock()
        repo = TimesheetRepository(mock_session)

        company_id = uuid.uuid4()
        manager_id = uuid.uuid4()
        mock_timesheets = [
            Timesheet(id=uuid.uuid4(), employee_id=uuid.uuid4(), week_start_date=date.today(), status="PENDING"),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_timesheets
        mock_session.execute.return_value = mock_result

        result = await repo.get_pending_timesheets(
            company_id=company_id,
            manager_employee_id=manager_id,
            role="manager"
        )
        assert len(result) == 1

        called_stmt = mock_session.execute.call_args[0][0]
        stmt_str = str(called_stmt)
        assert "company_id" in stmt_str
        assert "manager_id" in stmt_str or "reporting_manager_id" in stmt_str


class TestTimesheetServiceSecurity:
    """Test Timesheet service authorization and business logic."""

    @pytest.mark.asyncio
    async def test_get_or_create_weekly_timesheet_tenant_check(self):
        """Verify employee must belong to company."""
        mock_session = AsyncMock()
        service = TimesheetService(mock_session)

        company_id = uuid.uuid4()
        employee_id = uuid.uuid4()
        other_company_id = uuid.uuid4()

        # Employee not in company
        mock_emp_result = MagicMock()
        mock_emp_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_emp_result

        with pytest.raises(NotFoundException):
            await service.get_or_create_weekly_timesheet(employee_id, date.today(), company_id)

    @pytest.mark.asyncio
    async def test_submit_timesheet_requires_company_membership(self):
        """Verify submit_timesheet checks employee company membership."""
        mock_session = AsyncMock()
        service = TimesheetService(mock_session)

        company_id = uuid.uuid4()
        employee_id = uuid.uuid4()

        mock_emp_result = MagicMock()
        mock_emp_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_emp_result

        with pytest.raises(NotFoundException):
            await service.submit_timesheet(employee_id, date.today(), company_id)

    @pytest.mark.asyncio
    async def test_review_timesheet_prevents_self_approval(self):
        """Reviewer cannot approve their own timesheet."""
        mock_session = AsyncMock()
        service = TimesheetService(mock_session)

        company_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        timesheet_id = uuid.uuid4()

        # Timesheet owned by reviewer
        mock_timesheet = Timesheet(
            id=timesheet_id,
            employee_id=reviewer_id,  # Same as reviewer!
            week_start_date=date.today(),
            status="PENDING"
        )

        mock_repo_result = MagicMock()
        mock_repo_result.scalar_one_or_none.return_value = mock_timesheet
        mock_session.execute.return_value = mock_repo_result

        with pytest.raises(BadRequestException) as exc_info:
            await service.review_timesheet(
                timesheet_id=timesheet_id,
                status="APPROVED",
                approved_by_id=reviewer_id,
                company_id=company_id,
                reviewer_employee_id=reviewer_id,
                reviewer_role="manager"
            )
        assert "own" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_review_timesheet_manager_authority_check(self):
        """Manager can only review their direct reports."""
        mock_session = AsyncMock()
        service = TimesheetService(mock_session)

        company_id = uuid.uuid4()
        manager_id = uuid.uuid4()
        employee_id = uuid.uuid4()
        timesheet_id = uuid.uuid4()

        mock_timesheet = Timesheet(
            id=timesheet_id,
            employee_id=employee_id,
            week_start_date=date.today(),
            status="PENDING"
        )

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            manager_id=uuid.uuid4(),  # Different manager!
            reporting_manager_id=uuid.uuid4()
        )

        mock_repo_result = MagicMock()
        mock_repo_result.scalar_one_or_none.return_value = mock_timesheet
        mock_session.execute.return_value = mock_repo_result

        # Mock session.execute for employee lookup
        mock_emp_result = MagicMock()
        mock_emp_result.scalar_one_or_none.return_value = mock_employee
        
        # Need to handle multiple execute calls
        call_count = 0
        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_repo_result
            return mock_emp_result
        
        mock_session.execute.side_effect = execute_side_effect

        with pytest.raises(BadRequestException) as exc_info:
            await service.review_timesheet(
                timesheet_id=timesheet_id,
                status="APPROVED",
                approved_by_id=manager_id,
                company_id=company_id,
                reviewer_employee_id=manager_id,
                reviewer_role="manager"
            )
        assert "authorized" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_review_timesheet_concurrency_protection(self):
        """Concurrent review attempts are prevented."""
        mock_session = AsyncMock()
        service = TimesheetService(mock_session)

        company_id = uuid.uuid4()
        reviewer_id = uuid.uuid4()
        employee_id = uuid.uuid4()
        manager_id = uuid.uuid4()
        timesheet_id = uuid.uuid4()

        mock_timesheet = Timesheet(
            id=timesheet_id,
            employee_id=employee_id,
            week_start_date=date.today(),
            status="PENDING"
        )

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            manager_id=manager_id
        )

        mock_repo_result = MagicMock()
        mock_repo_result.scalar_one_or_none.return_value = mock_timesheet

        mock_emp_result = MagicMock()
        mock_emp_result.scalar_one_or_none.return_value = mock_employee

        call_count = 0
        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_repo_result
            if call_count == 2:
                return mock_emp_result
            # Third call is the refresh which should show status changed
            mock_refresh_result = MagicMock()
            mock_refresh_result.scalar_one_or_none.return_value = None
            return mock_refresh_result
        
        mock_session.execute.side_effect = execute_side_effect

        # Simulate status change during review by returning APPROVED after refresh
        original_refresh = mock_session.refresh
        async def mock_refresh(obj):
            obj.status = "APPROVED"  # Changed by concurrent reviewer!
        mock_session.refresh.side_effect = mock_refresh

        with pytest.raises(BadRequestException) as exc_info:
            await service.review_timesheet(
                timesheet_id=timesheet_id,
                status="APPROVED",
                approved_by_id=reviewer_id,
                company_id=company_id,
                reviewer_employee_id=reviewer_id,
                reviewer_role="manager"
            )
        assert "state changed" in str(exc_info.value.message).lower()


class TestTimesheetAPISecurity:
    """Test Timesheet API endpoint authorization."""

    @pytest.mark.asyncio
    async def test_get_pending_requires_manager_or_admin_role(self):
        """Only managers, HR admins, executives can access pending timesheets."""
        from app.api.timesheets import get_pending
        from app.core.exceptions import AppException

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",  # Not authorized
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        mock_company = Employee(
            id=uuid.uuid4(),
            company_id=company_id
        )

        with patch("app.api.timesheets.get_current_employee", return_value=mock_employee):
            with patch("app.api.timesheets.get_current_company", return_value=mock_company):
                with pytest.raises(AppException) as exc_info:
                    await get_pending(mock_claims, mock_session, mock_employee, mock_company)
                assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_review_timesheet_requires_manager_or_admin(self):
        """Only managers, HR admins, executives can review timesheets."""
        from app.api.timesheets import review_timesheet
        from app.core.exceptions import AppException
        from app.schemas.timesheet import TimesheetApprovalRequest

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",  # Not authorized
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        mock_company = Employee(
            id=uuid.uuid4(),
            company_id=company_id
        )

        review_body = TimesheetApprovalRequest(status="APPROVED", rejection_reason=None)

        with patch("app.api.timesheets.get_current_employee", return_value=mock_employee):
            with patch("app.api.timesheets.get_current_company", return_value=mock_company):
                with pytest.raises(AppException) as exc_info:
                    await review_timesheet(
                        uuid.uuid4(), review_body, mock_claims, mock_session, mock_employee, mock_company
                    )
                assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_employee_can_only_access_own_timesheet(self):
        """Employee endpoints only return current employee's data."""
        from app.api.timesheets import get_weekly_timesheet, get_history

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        mock_company = Employee(
            id=uuid.uuid4(),
            company_id=company_id
        )

        now = datetime.now()
        mock_timesheet = Timesheet(
            id=uuid.uuid4(),
            employee_id=employee_id,
            week_start_date=date.today(),
            status="DRAFT",
            created_at=now,
            updated_at=now
        )

        with patch("app.api.timesheets.get_current_employee", return_value=mock_employee):
            with patch("app.api.timesheets.get_current_company", return_value=mock_company):
                with patch("app.api.timesheets.TimesheetService") as mock_service_class:
                    mock_service = mock_service_class.return_value
                    mock_service.get_or_create_weekly_timesheet = AsyncMock(return_value=mock_timesheet)
                    mock_service.get_employee_timesheet_history = AsyncMock(return_value=[mock_timesheet])

                    response = await get_weekly_timesheet(date.today(), mock_claims, mock_session, mock_employee, mock_company)
                    assert response.success is True
                    mock_service.get_or_create_weekly_timesheet.assert_called_once_with(
                        employee_id, date.today(), company_id
                    )

                    response = await get_history(mock_claims, mock_session, mock_employee, mock_company)
                    assert response.success is True
                    mock_service.get_employee_timesheet_history.assert_called_once_with(
                        employee_id, company_id
                    )


class TestTimesheetCrossTenantIsolation:
    """Test cross-tenant isolation for timesheets."""

    @pytest.mark.asyncio
    async def test_company_a_cannot_see_company_b_timesheets(self):
        """Company A users cannot access Company B timesheets."""
        mock_session = AsyncMock()
        service = TimesheetService(mock_session)

        company_a = uuid.uuid4()
        company_b = uuid.uuid4()
        employee_b = uuid.uuid4()
        timesheet_id = uuid.uuid4()

        # Timesheet belongs to Company B employee
        mock_timesheet = Timesheet(
            id=timesheet_id,
            employee_id=employee_b,
            week_start_date=date.today(),
            status="PENDING"
        )

        mock_repo_result = MagicMock()
        mock_repo_result.scalar_one_or_none.return_value = mock_timesheet
        mock_session.execute.return_value = mock_repo_result

        # Company A employee tries to review Company B timesheet
        mock_employee_a = Employee(id=uuid.uuid4(), company_id=company_a)

        # The service should check employee company membership
        mock_emp_result = MagicMock()
        mock_emp_result.scalar_one_or_none.return_value = None  # Employee B not in Company A
        
        call_count = 0
        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_repo_result
            return mock_emp_result
        
        mock_session.execute.side_effect = execute_side_effect

        with pytest.raises(NotFoundException):
            await service.review_timesheet(
                timesheet_id=timesheet_id,
                status="APPROVED",
                approved_by_id=mock_employee_a.id,
                company_id=company_a,
                reviewer_employee_id=mock_employee_a.id,
                reviewer_role="hr_admin"
            )

    @pytest.mark.asyncio
    async def test_pending_timesheets_filtered_by_company(self):
        """Pending timesheets list only shows same-company timesheets."""
        mock_session = AsyncMock()
        repo = TimesheetRepository(mock_session)

        company_a = uuid.uuid4()
        company_b = uuid.uuid4()

        mock_timesheets_a = [
            Timesheet(id=uuid.uuid4(), employee_id=uuid.uuid4(), week_start_date=date.today(), status="PENDING"),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_timesheets_a
        mock_session.execute.return_value = mock_result

        result = await repo.get_pending_timesheets(company_id=company_a, role="hr_admin")
        assert len(result) == 1

        # Verify the query had company_a filter
        called_stmt = mock_session.execute.call_args[0][0]
        stmt_str = str(called_stmt)
        assert str(company_a) in stmt_str or "company_id" in stmt_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])