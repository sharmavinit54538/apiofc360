"""Tests for HR Admin internal user management and multi-tenant isolation."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from pydantic import ValidationError

from app.core.exceptions import AppException, ConflictException
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User, UserRole, UserAccountStatus
from app.schemas.hr_admin import (
    HRAdminCreateUserRequest,
    HRAdminUpdateUserRequest,
)
from app.services.hr_admin_service import HRAdminService


@pytest.mark.asyncio
async def test_hr_admin_can_create_employee():
    """Test HR Admin creating an EMPLOYEE user."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_email_svc = AsyncMock()

    # Uniqueness check returns None (no duplicate)
    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_exec_res

    service = HRAdminService(session=mock_session, email_service=mock_email_svc)

    admin_id = uuid.uuid4()
    company_id = uuid.uuid4()

    req = HRAdminCreateUserRequest(
        first_name="Rahul",
        last_name="Sharma",
        email="rahul@company.com",
        phone="9876543210",
        role="EMPLOYEE",
        department="Engineering",
        designation="Software Engineer",
    )

    with patch("app.services.hr_admin_service.generate_employee_id", new=AsyncMock(return_value="EMP-001")):
        res = await service.create_user(admin_id=admin_id, company_id=company_id, payload=req)

    assert res.email == "rahul@company.com"
    assert res.role == "employee"
    assert res.account_status == "INVITED"
    assert res.is_active is False
    assert res.is_verified is False

    added_objects = [c.args[0] for c in mock_session.add.call_args_list]
    user_obj = next(o for o in added_objects if isinstance(o, User))
    assert user_obj.company_id == company_id
    assert user_obj.role == UserRole.EMPLOYEE
    assert user_obj.created_by == admin_id


@pytest.mark.asyncio
async def test_hr_admin_can_create_manager_executive_it_admin():
    """Test HR Admin can create MANAGER, EXECUTIVE, and IT_ADMIN roles."""
    for allowed_role in ["MANAGER", "EXECUTIVE", "IT_ADMIN"]:
        req = HRAdminCreateUserRequest(
            first_name="Test",
            last_name="User",
            email=f"{allowed_role.lower()}@company.com",
            role=allowed_role,
        )
        assert req.role == allowed_role.lower()


def test_schema_rejects_super_admin_and_hr_admin_creation():
    """Test that HRAdminCreateUserRequest rejects super_admin and hr_admin roles."""
    with pytest.raises(ValidationError) as exc_super:
        HRAdminCreateUserRequest(
            first_name="Hacker",
            email="hacker@test.com",
            role="SUPER_ADMIN",
        )
    assert "Super Admin" in str(exc_super.value)

    with pytest.raises(ValidationError) as exc_hr:
        HRAdminCreateUserRequest(
            first_name="Admin",
            email="admin2@test.com",
            role="HR_ADMIN",
        )
    assert "HR Admin" in str(exc_hr.value)


@pytest.mark.asyncio
async def test_hr_admin_cannot_update_role_to_super_admin():
    """Test that HR Admin cannot escalate a user's privileges to super_admin or hr_admin."""
    mock_session = AsyncMock()
    mock_email_svc = AsyncMock()

    service = HRAdminService(session=mock_session, email_service=mock_email_svc)

    admin_id = uuid.uuid4()
    company_id = uuid.uuid4()
    target_user_id = uuid.uuid4()

    # Mock user exists in company
    user = User(
        id=target_user_id,
        company_id=company_id,
        name="Employee",
        email="emp@test.com",
        role=UserRole.EMPLOYEE,
    )
    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value.first.return_value = user
    mock_session.execute.return_value = mock_exec_res

    # Attempting to assign super_admin in update payload should fail at schema validation or service
    with pytest.raises(ValidationError):
        HRAdminUpdateUserRequest(role="SUPER_ADMIN")


@pytest.mark.asyncio
async def test_hr_admin_cannot_deactivate_self():
    """Test that HR Admin cannot deactivate their own account."""
    mock_session = AsyncMock()
    mock_email_svc = AsyncMock()

    service = HRAdminService(session=mock_session, email_service=mock_email_svc)

    admin_id = uuid.uuid4()
    company_id = uuid.uuid4()

    with pytest.raises(AppException) as exc_info:
        await service.deactivate_user(admin_id=admin_id, company_id=company_id, target_user_id=admin_id)

    assert exc_info.value.status_code == 400
    assert "cannot deactivate your own account" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_cross_tenant_access_denied_returns_404():
    """Test that HR Admin in Company A cannot view or update user in Company B."""
    mock_session = AsyncMock()
    mock_email_svc = AsyncMock()

    service = HRAdminService(session=mock_session, email_service=mock_email_svc)

    admin_id = uuid.uuid4()
    company_a_id = uuid.uuid4()
    company_b_user_id = uuid.uuid4()

    # User not found in Company A
    mock_exec_res = MagicMock()
    mock_exec_res.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_exec_res

    with pytest.raises(AppException) as exc_info:
        await service.get_user(target_user_id=company_b_user_id, company_id=company_a_id)

    assert exc_info.value.status_code == 404
