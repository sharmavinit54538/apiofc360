"""Tests for Employee Invitation -> Password Activation -> Onboarding flow backend audit.

Validates:
1. Employee self-activation via POST /api/v1/employees/{employee_id}/activate
2. Activation token validity and one-time use (token invalidation upon activation)
3. Secure password hashing with bcrypt
4. User creation/linking when employee.user_id is None
5. Password complexity & confirmation match validation
6. Onboarding API authorization (JWT Bearer required, active profile required)
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from pydantic import ValidationError

from app.models.employee import Employee
from app.models.user import User, UserRole
from app.core.exceptions import AppException
from app.core.security import verify_password
from app.services.employee_service import EmployeeService
from app.schemas.employee.onboarding import ActivateEmployeeRequest, ActivateOnboardingRequest


# ==============================================================================
# 1. Schema Validation Tests (Password Complexity & Matching)
# ==============================================================================

def test_activate_employee_request_valid():
    """Valid token and matching strong password should pass validation."""
    req = ActivateEmployeeRequest(
        token="valid_activation_token_12345",
        new_password="Password@2026",
        confirm_password="Password@2026",
    )
    assert req.token == "valid_activation_token_12345"
    assert req.new_password == "Password@2026"


def test_activate_employee_request_password_mismatch():
    """Mismatched passwords must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ActivateEmployeeRequest(
            token="valid_activation_token_12345",
            new_password="Password@2026",
            confirm_password="DifferentPassword@2026",
        )
    assert "Passwords do not match" in str(exc_info.value)


def test_activate_employee_request_weak_password():
    """Weak password (no uppercase/digit/special) must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ActivateEmployeeRequest(
            token="valid_activation_token_12345",
            new_password="weakpassword",
            confirm_password="weakpassword",
        )
    assert "Password must contain" in str(exc_info.value) or "8 characters" in str(exc_info.value)


def test_activate_onboarding_request_password_complexity():
    """ActivateOnboardingRequest password must enforce complexity."""
    with pytest.raises(ValidationError):
        ActivateOnboardingRequest(
            token="valid_token_12345",
            password="weak",
        )


# ==============================================================================
# 2. Employee Service Activation Logic Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_activate_employee_success_creates_user_and_invalidates_token():
    """Verify that activate_employee creates a user row, securely hashes password, and clears token."""
    session = AsyncMock()
    session.add = MagicMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()

    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()
    token = "secret_activation_token_xyz12345"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    mock_emp = Employee(
        id=emp_id,
        user_id=None,  # Not yet linked
        company_id=company_id,
        employee_id="EMP-2026-001",
        first_name="Ravi",
        last_name="Sharma",
        personal_email="ravi.sharma@example.com",
        company_email="ravi.sharma@ofc360.com",
        phone="9876543210",
        role="employee",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    repo.get_by_id_raw.return_value = mock_emp

    # Mock execute queries for user lookup (no existing user by ID or email, no phone collision)
    mock_result_empty = MagicMock()
    mock_result_empty.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result_empty

    payload = ActivateEmployeeRequest(
        token=token,
        new_password="SecurePassword@2026",
        confirm_password="SecurePassword@2026",
    )

    await service.activate_employee(emp_id, payload)

    # 1. Verify User was created and added to session
    assert session.add.called
    added_user = None
    for call_args in session.add.call_args_list:
        obj = call_args[0][0]
        if isinstance(obj, User):
            added_user = obj
            break

    assert added_user is not None
    assert added_user.email == "ravi.sharma@ofc360.com"
    assert added_user.is_active is True
    assert added_user.is_verified is True
    assert added_user.must_change_password is False
    assert added_user.account_status == "ACTIVE"
    # Verify password was hashed with bcrypt
    assert verify_password("SecurePassword@2026", added_user.password_hash) is True

    # 2. Verify token was invalidated
    assert mock_emp.activation_token is None
    assert mock_emp.activation_token_expires_at is None
    assert mock_emp.status == "ONBOARDING_PENDING"
    assert mock_emp.is_active is True

    # 3. Verify transaction commit
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_employee_invalid_token_rejected():
    """Verify that an invalid token is rejected with 400 Bad Request."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()

    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    emp_id = uuid.uuid4()
    mock_emp = Employee(
        id=emp_id,
        user_id=None,
        company_id=uuid.uuid4(),
        employee_id="EMP-001",
        first_name="Ravi",
        last_name="Sharma",
        personal_email="ravi@example.com",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token="correct_token_12345",
        activation_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    repo.get_by_id_raw.return_value = mock_emp

    payload = ActivateEmployeeRequest(
        token="wrong_token_54321",
        new_password="SecurePassword@2026",
        confirm_password="SecurePassword@2026",
    )

    with pytest.raises(AppException) as exc_info:
        await service.activate_employee(emp_id, payload)

    assert exc_info.value.status_code == 400
    assert "Invalid activation token" in exc_info.value.message


@pytest.mark.asyncio
async def test_activate_employee_expired_token_rejected():
    """Verify that an expired activation token is rejected with 400 Bad Request."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()

    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    emp_id = uuid.uuid4()
    mock_emp = Employee(
        id=emp_id,
        user_id=None,
        company_id=uuid.uuid4(),
        employee_id="EMP-001",
        first_name="Ravi",
        last_name="Sharma",
        personal_email="ravi@example.com",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token="token_xyz_12345",
        # Expired 2 hours ago
        activation_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    repo.get_by_id_raw.return_value = mock_emp

    payload = ActivateEmployeeRequest(
        token="token_xyz_12345",
        new_password="SecurePassword@2026",
        confirm_password="SecurePassword@2026",
    )

    with pytest.raises(AppException) as exc_info:
        await service.activate_employee(emp_id, payload)

    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_activate_employee_token_reuse_prevented():
    """Verify that once a token is invalidated (None), reuse is rejected with 400."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()

    service = EmployeeService(
        session=session,
        employee_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    emp_id = uuid.uuid4()
    mock_emp = Employee(
        id=emp_id,
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        employee_id="EMP-001",
        first_name="Ravi",
        last_name="Sharma",
        personal_email="ravi@example.com",
        status="ACTIVE",  # Already activated
        is_active=True,
        is_deleted=False,
        activation_token=None,  # Token was cleared
        activation_token_expires_at=None,
    )
    repo.get_by_id_raw.return_value = mock_emp

    payload = ActivateEmployeeRequest(
        token="already_used_token_12345",
        new_password="SecurePassword@2026",
        confirm_password="SecurePassword@2026",
    )

    with pytest.raises(AppException) as exc_info:
        await service.activate_employee(emp_id, payload)

    assert exc_info.value.status_code == 400
    assert "No activation token found" in exc_info.value.message or "already" in exc_info.value.message


# ==============================================================================
# 3. Employee Onboarding Authorization Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_onboarding_access_requires_valid_employee():
    """Helper get_current_employee in employee_onboarding_api requires employee profile linked to user_id."""
    from app.api.employee_onboarding_api import get_current_employee
    from fastapi import HTTPException

    db = AsyncMock()
    user_id = uuid.uuid4()
    claims = {"sub": str(user_id), "role": "EMPLOYEE"}

    # Mock employee not found for this user
    with patch("app.api.employee_onboarding_api.EmployeeOnboardingService") as mock_svc_cls:
        mock_svc = AsyncMock()
        mock_svc.get_employee_by_user_id.return_value = None
        mock_svc_cls.return_value = mock_svc

        with pytest.raises(HTTPException) as exc_info:
            await get_current_employee(claims=claims, db=db)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_onboarding_access_succeeds_for_active_linked_employee():
    """Helper get_current_employee returns employee for active authenticated employee."""
    from app.api.employee_onboarding_api import get_current_employee

    db = AsyncMock()
    user_id = uuid.uuid4()
    claims = {"sub": str(user_id), "role": "EMPLOYEE"}

    mock_emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        first_name="Ravi",
        last_name="Sharma",
        personal_email="ravi@example.com",
        status="ONBOARDING_PENDING",
        is_active=True,
    )

    with patch("app.api.employee_onboarding_api.EmployeeOnboardingService") as mock_svc_cls:
        mock_svc = AsyncMock()
        mock_svc.get_employee_by_user_id.return_value = mock_emp
        mock_svc_cls.return_value = mock_svc

        emp = await get_current_employee(claims=claims, db=db)
        assert emp.id == mock_emp.id
        assert emp.user_id == user_id
