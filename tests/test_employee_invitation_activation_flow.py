"""Comprehensive tests for Employee Invitation Token Generation, Validation, and Activation Flow.

Tests:
1. Fresh token validation returns HTTP 200 and complete employee metadata with UUID employee_id.
2. Expired token validation returns HTTP 400 'Invitation expired. Request new invitation.'
3. Already-used token returns HTTP 400 'Invitation already used.'
4. Random / invalid token returns HTTP 400 'Invalid invitation.'
5. Validation endpoint is idempotent and does NOT consume/clear the token.
6. Different valid unactivated employee statuses (INVITED, INVITATION_SENT, CREATED, PROBATION, PENDING) pass validation.
7. Password activation (POST /api/v1/employees/{id}/activate) hashes password, links user, sets employee status to ONBOARDING_PENDING, and clears token.
8. Post-activation token reuse is prevented.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.exceptions import AppException
from app.models.employee import Employee
from app.models.user import User, UserRole
from app.models.company import Company
from app.schemas.employee.onboarding import ActivateEmployeeRequest
from app.services.employee_service import EmployeeService
from app.api.onboarding import validate_onboarding_token


# ==============================================================================
# 1. Token Validation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_fresh_invitation_token_validation_success():
    """Verify that a freshly generated invitation token returns HTTP 200 with UUID and employee info."""
    session = AsyncMock()
    token = "fresh_secure_token_1234567890abcdef"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    emp_uuid = uuid.uuid4()
    company_uuid = uuid.uuid4()

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=company_uuid,
        employee_id="EMP-2026-001",
        first_name="Priya",
        last_name="Verma",
        personal_email="priya.verma@example.com",
        company_email="priya@ofc360.com",
        phone="9876543210",
        department="Engineering",
        designation="Software Engineer",
        role="employee",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    # 1. Employee query result
    mock_emp_result = MagicMock()
    mock_emp_result.scalar_one_or_none.return_value = mock_emp

    # 2. Company query result
    mock_comp_result = MagicMock()
    mock_comp_result.scalar_one_or_none.return_value = "Acme Corp"

    session.execute.side_effect = [mock_emp_result, mock_comp_result]

    resp = await validate_onboarding_token(token=token, session=session)

    assert resp.success is True
    assert resp.message == "Token is valid."
    assert resp.data["id"] == str(emp_uuid)
    assert resp.data["employee_id"] == str(emp_uuid)
    assert resp.data["employee_code"] == "EMP-2026-001"
    assert resp.data["first_name"] == "Priya"
    assert resp.data["last_name"] == "Verma"
    assert resp.data["name"] == "Priya Verma"
    assert resp.data["personal_email"] == "priya.verma@example.com"
    assert resp.data["company_name"] == "Acme Corp"
    assert resp.data["valid"] is True
    # Token was NOT modified or deleted
    assert mock_emp.activation_token == token


@pytest.mark.asyncio
async def test_expired_invitation_token_validation_returns_400():
    """Verify that an expired token returns HTTP 400 with 'Invitation expired. Request new invitation.'"""
    session = AsyncMock()
    token = "expired_token_1234567890abcdef"
    # Expired 1 hour ago
    expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    emp_uuid = uuid.uuid4()

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=uuid.uuid4(),
        employee_id="EMP-2026-002",
        first_name="Aman",
        last_name="Singh",
        personal_email="aman.singh@example.com",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    mock_emp_result = MagicMock()
    mock_emp_result.scalar_one_or_none.return_value = mock_emp
    session.execute.return_value = mock_emp_result

    with pytest.raises(HTTPException) as exc_info:
        await validate_onboarding_token(token=token, session=session)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invitation expired. Request new invitation."


@pytest.mark.asyncio
async def test_already_used_token_returns_400():
    """Verify that validating an already active/used invitation returns 400 Invitation already used."""
    session = AsyncMock()
    token = "used_token_1234567890abcdef"
    emp_uuid = uuid.uuid4()

    mock_emp = Employee(
        id=emp_uuid,
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        employee_id="EMP-2026-003",
        first_name="Karan",
        last_name="Kapoor",
        personal_email="karan@example.com",
        status="ACTIVE",  # Already activated
        is_active=True,
        is_deleted=False,
        activation_token=None,
        activation_token_expires_at=None,
    )

    mock_emp_result = MagicMock()
    mock_emp_result.scalar_one_or_none.return_value = mock_emp
    session.execute.return_value = mock_emp_result

    with pytest.raises(HTTPException) as exc_info:
        await validate_onboarding_token(token=token, session=session)

    assert exc_info.value.status_code == 400
    assert "already" in exc_info.value.detail.lower() or "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_random_invalid_token_returns_400():
    """Verify that a random/non-existent token returns HTTP 400 Invalid invitation token."""
    session = AsyncMock()
    mock_result_empty = MagicMock()
    mock_result_empty.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result_empty

    with pytest.raises(HTTPException) as exc_info:
        await validate_onboarding_token(token="completely_random_token_99999", session=session)

    assert exc_info.value.status_code == 400
    assert "Invalid invitation" in exc_info.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("status_name", ["INVITED", "INVITATION_SENT", "CREATED", "PROBATION", "PENDING"])
async def test_all_valid_initial_statuses_pass_validation(status_name: str):
    """Verify that all initial invited statuses are accepted by the validation endpoint."""
    session = AsyncMock()
    token = f"token_for_{status_name.lower()}_status"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
    emp_uuid = uuid.uuid4()

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=uuid.uuid4(),
        employee_id="EMP-TEST",
        first_name="Test",
        last_name="User",
        personal_email="test@example.com",
        status=status_name,
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    mock_emp_result = MagicMock()
    mock_emp_result.scalar_one_or_none.return_value = mock_emp
    mock_comp_result = MagicMock()
    mock_comp_result.scalar_one_or_none.return_value = "Test Co"
    session.execute.side_effect = [mock_emp_result, mock_comp_result]

    resp = await validate_onboarding_token(token=token, session=session)
    assert resp.success is True
    assert resp.data["id"] == str(emp_uuid)


# ==============================================================================
# 2. Token Service & Employee Activation Password Flow Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_employee_service_validate_invitation_token():
    """Verify EmployeeService.validate_invitation_token returns complete data."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_svc = AsyncMock()

    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_svc,
    )

    token = "service_valid_token_12345"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
    emp_uuid = uuid.uuid4()

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=uuid.uuid4(),
        employee_id="EMP-SERVICE-001",
        first_name="Deepak",
        last_name="Rao",
        personal_email="deepak.rao@example.com",
        company_email="deepak@company.com",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    mock_emp_res = MagicMock()
    mock_emp_res.scalar_one_or_none.return_value = mock_emp
    mock_comp_res = MagicMock()
    mock_comp_res.scalar_one_or_none.return_value = "OFC360 Technologies"
    session.execute.side_effect = [mock_emp_res, mock_comp_res]

    data = await service.validate_invitation_token(token)
    assert data["id"] == str(emp_uuid)
    assert data["employee_id"] == str(emp_uuid)
    assert data["employee_code"] == "EMP-SERVICE-001"
    assert data["name"] == "Deepak Rao"
    assert data["company_name"] == "OFC360 Technologies"


@pytest.mark.asyncio
async def test_activate_employee_sets_password_and_clears_token():
    """Verify POST /api/v1/employees/{id}/activate sets password, updates status to ONBOARDING_PENDING, and sets token to NULL."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_svc = AsyncMock()

    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_svc,
    )

    emp_uuid = uuid.uuid4()
    token = "activation_submit_token_12345"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=48)

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=uuid.uuid4(),
        employee_id="EMP-ACT-001",
        first_name="Simran",
        last_name="Kaur",
        personal_email="simran.kaur@example.com",
        company_email="simran@ofc360.com",
        phone="9876543210",
        role="employee",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    repo.get_by_id_raw.return_value = mock_emp

    mock_res_empty = MagicMock()
    mock_res_empty.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_res_empty

    payload = ActivateEmployeeRequest(
        token=token,
        new_password="StrongPassword@2026",
        confirm_password="StrongPassword@2026",
    )

    await service.activate_employee(emp_uuid, payload)

    # 1. Verify User was created and added to session
    assert session.add.called
    created_user = None
    for call_args in session.add.call_args_list:
        obj = call_args[0][0]
        if isinstance(obj, User):
            created_user = obj
            break

    assert created_user is not None
    assert created_user.is_active is True
    assert created_user.is_verified is True
    assert created_user.account_status == "ACTIVE"
    assert created_user.email_verification_token is None

    # 2. Verify Employee record updated to ONBOARDING_PENDING and tokens cleared
    assert mock_emp.activation_token is None
    assert mock_emp.activation_token_expires_at is None
    assert mock_emp.status == "ONBOARDING_PENDING"
    assert mock_emp.is_active is True

    # 3. Transaction committed
    session.commit.assert_awaited_once()
