"""Security tests for Travel Management API - Tenant isolation, authorization, workflow enforcement."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from sqlalchemy import select

from app.api.v2.travel_api import (
    _validate_travel_status_transition,
    _validate_approver_authority,
    TRAVEL_STATUS_WORKFLOW,
    STAGE_APPROVER_ROLES,
)
from app.models.employee import Employee
from app.models.travel import TravelRequest
from app.models.company import Company
from app.models.user import User
from app.models.user.role import RoleEnum
from app.repositories.employee_repository import EmployeeRepository


class TestTravelWorkflowValidation:
    """Test travel status workflow transitions and approver authority."""

    def test_valid_status_transitions(self):
        """Test all valid status transitions per workflow."""
        # Draft can go to manager-review or cancelled
        assert _validate_travel_status_transition("draft", "manager-review") is True
        assert _validate_travel_status_transition("draft", "cancelled") is True
        assert _validate_travel_status_transition("draft", "approved") is False
        assert _validate_travel_status_transition("draft", "hr-review") is False

        # Manager-review can go to hr-review, finance-review, rejected, draft
        assert _validate_travel_status_transition("manager-review", "hr-review") is True
        assert _validate_travel_status_transition("manager-review", "finance-review") is True
        assert _validate_travel_status_transition("manager-review", "rejected") is True
        assert _validate_travel_status_transition("manager-review", "draft") is True
        assert _validate_travel_status_transition("manager-review", "approved") is False

        # HR-review can go to finance-review, approved, rejected, manager-review
        assert _validate_travel_status_transition("hr-review", "finance-review") is True
        assert _validate_travel_status_transition("hr-review", "approved") is True
        assert _validate_travel_status_transition("hr-review", "rejected") is True
        assert _validate_travel_status_transition("hr-review", "manager-review") is True

        # Finance-review can go to approved, rejected, hr-review
        assert _validate_travel_status_transition("finance-review", "approved") is True
        assert _validate_travel_status_transition("finance-review", "rejected") is True
        assert _validate_travel_status_transition("finance-review", "hr-review") is True

        # Approved can only go to rejected
        assert _validate_travel_status_transition("approved", "rejected") is True
        assert _validate_travel_status_transition("approved", "draft") is False

        # Rejected can go to draft
        assert _validate_travel_status_transition("rejected", "draft") is True

        # Cancelled can go to draft
        assert _validate_travel_status_transition("cancelled", "draft") is True

    def test_invalid_status_transitions(self):
        """Test invalid status transitions are rejected."""
        assert _validate_travel_status_transition("draft", "invalid") is False
        assert _validate_travel_status_transition("invalid", "draft") is False
        assert _validate_travel_status_transition("approved", "manager-review") is False

    def test_approver_authority_valid(self):
        """Test valid approver roles for each stage."""
        # Manager-review: manager, hr_admin, executive
        assert _validate_approver_authority("manager", "manager-review") is True
        assert _validate_approver_authority("hr_admin", "manager-review") is True
        assert _validate_approver_authority("executive", "manager-review") is True
        assert _validate_approver_authority("employee", "manager-review") is False

        # HR-review: hr_admin, executive
        assert _validate_approver_authority("hr_admin", "hr-review") is True
        assert _validate_approver_authority("executive", "hr-review") is True
        assert _validate_approver_authority("manager", "hr-review") is False

        # Finance-review: hr_admin, executive, finance
        assert _validate_approver_authority("hr_admin", "finance-review") is True
        assert _validate_approver_authority("executive", "finance-review") is True
        assert _validate_approver_authority("finance", "finance-review") is True
        assert _validate_approver_authority("manager", "finance-review") is False

        # Approved: hr_admin, executive, manager, finance
        assert _validate_approver_authority("hr_admin", "approved") is True
        assert _validate_approver_authority("executive", "approved") is True
        assert _validate_approver_authority("manager", "approved") is True
        assert _validate_approver_authority("finance", "approved") is True

        # Rejected: manager, hr_admin, executive, finance
        assert _validate_approver_authority("manager", "rejected") is True
        assert _validate_approver_authority("hr_admin", "rejected") is True
        assert _validate_approver_authority("executive", "rejected") is True
        assert _validate_approver_authority("finance", "rejected") is True
        assert _validate_approver_authority("employee", "rejected") is False


class TestTravelRepositoryTenantIsolation:
    """Test Travel API tenant isolation at repository level using mocks."""

    @pytest.mark.asyncio
    async def test_list_travel_requests_tenant_isolation(self):
        """Verify list_travel_requests filters by company_id."""
        from app.api.v2.travel_api import list_travel_requests
        from app.schemas.auth import APIResponse

        # Setup mocks
        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()
        travel_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        mock_travel = TravelRequest(
            id=travel_id,
            employee_id=employee_id,
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_employee,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_travel]
        mock_session.execute.return_value = mock_result

        # Mock get_current_employee and get_current_company
        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
                response = await list_travel_requests(
                    status_filter=None,
                    search=None,
                    page=1,
                    limit=100,
                    claims=mock_claims,
                    db=mock_session,
                    current_employee=mock_employee,
                    current_company=mock_employee
                )

        assert response.success is True
        assert len(response.data) == 1
        
        # Verify query included company_id filter
        called_stmt = mock_session.execute.call_args[0][0]
        stmt_str = str(called_stmt)
        assert "company_id" in stmt_str

    @pytest.mark.asyncio
    async def test_get_travel_stats_tenant_isolation(self):
        """Verify get_travel_stats filters by company_id."""
        from app.api.v2.travel_api import get_travel_stats

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

        # Mock count queries
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_count_result

        # Mock budget sum
        mock_budget_result = MagicMock()
        mock_budget_result.scalar.return_value = Decimal("50000")
        
        # We need to handle multiple execute calls
        async def execute_side_effect(stmt):
            stmt_str = str(stmt).lower()
            if "sum" in stmt_str and "budget" in stmt_str:
                return mock_budget_result
            return mock_count_result
        
        mock_session.execute.side_effect = execute_side_effect

        with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
            response = await get_travel_stats(
                claims=mock_claims,
                db=mock_session,
                current_company=mock_employee
            )

        assert response.success is True
        assert response.data.total == 5
        assert response.data.budget == 50000.0

        # Verify all queries had company_id filter
        for call in mock_session.execute.call_args_list:
            called_stmt = call[0][0]
            stmt_str = str(called_stmt)
            assert "company_id" in stmt_str


class TestTravelAPISecurity:
    """Test Travel API authorization and security checks."""

    @pytest.mark.asyncio
    async def test_create_travel_request_self_only(self):
        """Employee can only create travel request for themselves."""
        from app.api.v2.travel_api import create_travel_request, TravelRequestCreate

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()
        travel_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        # Mock the database response for the created travel request
        mock_created_travel = TravelRequest(
            id=travel_id,
            employee_id=employee_id,
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_employee,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            history=[{"stage": "draft", "at": datetime.now().isoformat(), "note": "Created travel request"}]
        )

        # Mock execute for the reload query
        mock_reload_result = MagicMock()
        mock_reload_result.scalar_one.return_value = mock_created_travel
        mock_session.execute.return_value = mock_reload_result

        # Mock get_current_employee
        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            body = TravelRequestCreate(
                type="domestic",
                purpose="Meeting",
                destination="Mumbai",
                travel_date=date.today(),
                return_date=date.today(),
                budget=Decimal("10000"),
                currency="INR",
                hotel=None,
                transportation=None
            )

            # This should succeed - employee creating for themselves
            response = await create_travel_request(body, mock_claims, mock_session, mock_employee)
            assert response.success is True

    @pytest.mark.asyncio
    async def test_update_travel_request_owner_only(self):
        """Only travel request owner can update in draft/rejected state."""
        from app.api.v2.travel_api import update_travel_request, TravelRequestUpdate

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()
        travel_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        mock_travel = TravelRequest(
            id=travel_id,
            employee_id=employee_id,  # Owned by current employee
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_employee,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            history=[{"stage": "draft", "at": datetime.now().isoformat(), "note": "Created"}]
        )

        # Mock the first query (fetch travel request)
        mock_fetch_result = MagicMock()
        mock_fetch_result.scalar_one_or_none.return_value = mock_travel

        # Mock the reload query
        mock_reload_result = MagicMock()
        mock_updated_travel = TravelRequest(
            id=travel_id,
            employee_id=employee_id,
            type="domestic",
            purpose="Updated purpose",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_employee,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            history=[{"stage": "draft", "at": datetime.now().isoformat(), "note": "Created"}]
        )
        mock_reload_result.scalar_one.return_value = mock_updated_travel

        call_count = 0
        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_fetch_result
            return mock_reload_result
        
        mock_session.execute.side_effect = execute_side_effect

        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
                body = TravelRequestUpdate(
                    purpose="Updated purpose"
                )

                response = await update_travel_request(
                    travel_id, body, mock_claims, mock_session, mock_employee, mock_employee
                )
                assert response.success is True

    @pytest.mark.asyncio
    async def test_update_travel_request_other_employee_forbidden(self):
        """Employee cannot update another employee's travel request."""
        from app.api.v2.travel_api import update_travel_request
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "employee",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()
        other_employee_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001"
        )

        mock_other_employee = Employee(
            id=other_employee_id,
            company_id=company_id,
            first_name="Jane",
            last_name="Smith",
            employee_id="EMP-002"
        )

        mock_travel = TravelRequest(
            id=uuid.uuid4(),
            employee_id=other_employee_id,  # Owned by OTHER employee
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_other_employee
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_travel
        mock_session.execute.return_value = mock_result

        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
                body = MagicMock()
                body.type = None
                body.purpose = "Updated purpose"
                body.destination = None
                body.travel_date = None
                body.return_date = None
                body.budget = None
                body.currency = None
                body.hotel = None
                body.transportation = None

                with pytest.raises(HTTPException) as exc_info:
                    await update_travel_request(
                        mock_travel.id, body, mock_claims, mock_session, mock_employee, mock_employee
                    )
                assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_advance_travel_request_self_approval_forbidden(self):
        """Employee cannot approve their own travel request."""
        from app.api.v2.travel_api import advance_travel_request
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "manager",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        employee_id = uuid.uuid4()

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001",
            role="manager"
        )

        mock_travel = TravelRequest(
            id=uuid.uuid4(),
            employee_id=employee_id,  # Same employee!
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="manager-review",
            employee=mock_employee
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_travel
        mock_session.execute.return_value = mock_result

        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
                body = MagicMock()
                body.stage = "approved"
                body.note = "Approved"

                with pytest.raises(HTTPException) as exc_info:
                    await advance_travel_request(
                        mock_travel.id, body, mock_claims, mock_session, mock_employee, mock_employee
                    )
                assert exc_info.value.status_code == 403
                assert "own" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_advance_travel_request_manager_authority_required(self):
        """Only authorized manager can advance to manager-review."""
        from app.api.v2.travel_api import advance_travel_request
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_claims = {
            "sub": str(uuid.uuid4()),
            "role": "manager",
            "company_id": str(uuid.uuid4()),
        }
        company_id = uuid.UUID(mock_claims["company_id"])
        manager_id = uuid.uuid4()
        employee_id = uuid.uuid4()

        mock_manager = Employee(
            id=manager_id,
            company_id=company_id,
            first_name="Manager",
            last_name="User",
            employee_id="EMP-MGR",
            role="manager"
        )

        mock_employee = Employee(
            id=employee_id,
            company_id=company_id,
            first_name="John",
            last_name="Doe",
            employee_id="EMP-001",
            manager_id=uuid.uuid4(),  # Different manager!
            reporting_manager_id=uuid.uuid4()
        )

        mock_travel = TravelRequest(
            id=uuid.uuid4(),
            employee_id=employee_id,
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_employee
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_travel
        mock_session.execute.return_value = mock_result

        # Mock _check_reporting_relationship to return False
        with patch("app.api.v2.travel_api._check_reporting_relationship", return_value=False):
            with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_manager):
                with patch("app.api.v2.travel_api.get_current_company", return_value=mock_manager):
                    body = MagicMock()
                    body.stage = "manager-review"
                    body.note = "Submitted for review"

                    with pytest.raises(HTTPException) as exc_info:
                        await advance_travel_request(
                            mock_travel.id, body, mock_claims, mock_session, mock_manager, mock_manager
                        )
                    assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_travel_request_owner_only_draft(self):
        """Only owner can delete draft travel requests."""
        from app.api.v2.travel_api import delete_travel_request
        from fastapi import HTTPException

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

        mock_travel = TravelRequest(
            id=uuid.uuid4(),
            employee_id=employee_id,
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="draft",
            employee=mock_employee
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_travel
        mock_session.execute.return_value = mock_result

        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
                response = await delete_travel_request(
                    mock_travel.id, mock_claims, mock_session, mock_employee, mock_employee
                )
                assert response.success is True
                mock_session.delete.assert_called_once_with(mock_travel)

    @pytest.mark.asyncio
    async def test_delete_travel_request_non_draft_forbidden(self):
        """Cannot delete non-draft travel requests."""
        from app.api.v2.travel_api import delete_travel_request
        from fastapi import HTTPException

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

        mock_travel = TravelRequest(
            id=uuid.uuid4(),
            employee_id=employee_id,
            type="domestic",
            purpose="Meeting",
            destination="Mumbai",
            travel_date=date.today(),
            return_date=date.today(),
            budget=Decimal("10000"),
            currency="INR",
            status="manager-review",  # Not draft!
            employee=mock_employee
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_travel
        mock_session.execute.return_value = mock_result

        with patch("app.api.v2.travel_api.get_current_employee", return_value=mock_employee):
            with patch("app.api.v2.travel_api.get_current_company", return_value=mock_employee):
                with pytest.raises(HTTPException) as exc_info:
                    await delete_travel_request(
                        mock_travel.id, mock_claims, mock_session, mock_employee, mock_employee
                    )
                assert exc_info.value.status_code == 403


class TestTravelV1V2RouteRegistration:
    """Test that v1 and v2 travel routes don't have double prefix."""

    def test_travel_v1_router_includes_v2_without_prefix(self):
        """Verify v1 travel router includes v2 router with empty prefix."""
        from app.api.v1.travel import router as v1_travel_router
        
        # Check that v1 router includes v2 router
        included_routers = v1_travel_router.routes
        assert len(included_routers) > 0
        
        # The v1 router has prefix "/travel", v2 router has prefix "/travel"
        # When included with prefix="", the final paths should be /travel/... not /travel/travel/...
        for route in included_routers:
            if hasattr(route, 'path'):
                # Routes from included router should not have double /travel/travel
                assert not route.path.startswith("/travel/travel")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])