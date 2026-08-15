"""Comprehensive automated test suite for OFC360 user registration API."""

import pytest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.models.user import User, UserRole
from app.models.company import Company
from app.models.employee import Employee
from app.models.department import Department
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.otp import OTP
from app.schemas.auth import RegisterRequest, RegisterResponse, APIResponse
from app.services.auth_service import AuthService
from app.core.security import verify_password


# ============================================================================
# 1. Payload Preprocessing and Validation Tests
# ============================================================================

def test_register_payload_with_all_aliases():
    """Test payload with first_name, last_name, full_name, company_name, and phone aliases."""
    payload_data = {
        "first_name": "vinit",
        "last_name": "sharma",
        "name": "vinit sharma",
        "full_name": "vinit sharma",
        "company_name": "EquinoxSphere",
        "email": "test@example.com",
        "password": "Test@123456",
        "phone": "9999999999",
    }
    req = RegisterRequest.model_validate(payload_data)
    assert req.name == "vinit sharma"
    assert req.email == "test@example.com"
    assert req.phone == "9999999999"
    assert req.company_name == "EquinoxSphere"


def test_register_payload_first_last_without_name():
    """Test payload with first_name and last_name constructing name."""
    payload_data = {
        "first_name": "John",
        "last_name": "Doe",
        "company": "Acme Corp",
        "email": "john.doe@example.com",
        "password": "Password@123",
        "phone_number": "+91 9876543210",
    }
    req = RegisterRequest.model_validate(payload_data)
    assert req.name == "John Doe"
    assert req.company_name == "Acme Corp"
    assert req.phone == "9876543210"


def test_register_payload_organization_alias():
    """Test payload with organization_name and mobile aliases."""
    payload_data = {
        "full_name": "Alice Smith",
        "organization_name": "Tech Corp",
        "email": "alice@example.com",
        "password": "Password@123",
        "mobile": "09876543210",
    }
    req = RegisterRequest.model_validate(payload_data)
    assert req.name == "Alice Smith"
    assert req.company_name == "Tech Corp"
    assert req.phone == "9876543210"


def test_register_payload_invalid_email():
    """Test invalid email format raises validation error."""
    payload_data = {
        "name": "Vinit Sharma",
        "email": "invalid-email-format",
        "phone": "9876543210",
        "password": "Password@123",
        "company_name": "Acme Corp",
    }
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest.model_validate(payload_data)
    assert any("email" in str(e["loc"]) for e in exc_info.value.errors())


def test_register_payload_weak_password():
    """Test weak / simple password raises validation error."""
    payload_data = {
        "name": "Vinit Sharma",
        "email": "vinit@example.com",
        "phone": "9876543210",
        "password": "12345678",
        "company_name": "Acme Corp",
    }
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest.model_validate(payload_data)
    assert any("Password" in str(e["msg"]) for e in exc_info.value.errors())


def test_register_payload_password_containing_username():
    """Test password containing user's email username is rejected."""
    payload_data = {
        "name": "Vinit Sharma",
        "email": "vinits@example.com",
        "phone": "9876543210",
        "password": "vinitsPassword@123",
        "company_name": "Acme Corp",
    }
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest.model_validate(payload_data)
    assert any("username" in str(e["msg"]).lower() for e in exc_info.value.errors())


def test_register_payload_missing_required_fields():
    """Test missing required fields raise validation error."""
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate({"name": "Test"})


# ============================================================================
# 2. AuthService Business Logic & Flow Tests
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_auth_service_successful_registration_flow():
    """Test full registration logic: Company, User, Employee, Departments, Leave Policies, OTP, Email."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    # User does not exist
    mock_repo.get_user_by_email.return_value = None
    mock_repo.get_user_by_phone.return_value = None

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    payload = RegisterRequest.model_validate({
        "first_name": "vinit",
        "last_name": "sharma",
        "name": "vinit sharma",
        "full_name": "vinit sharma",
        "company_name": "EquinoxSphere",
        "email": "vinit.sharma@example.com",
        "password": "SecurePassword@123456",
        "phone": "9999999999",
    })

    with patch("app.utils.employee.generate_employee_id", new=AsyncMock(return_value="EMP-202608-0001")):
        await service.register_user(payload)

    added_objects = [c.args[0] for c in mock_session.add.call_args_list]

    # 1. Verify Company was created
    companies = [obj for obj in added_objects if isinstance(obj, Company)]
    assert len(companies) == 1
    company = companies[0]
    assert company.name == "EquinoxSphere"

    # 2. Verify User was created as HR_ADMIN (pending email verification)
    users = [obj for obj in added_objects if isinstance(obj, User)]
    assert len(users) == 1
    user = users[0]
    assert user.company_id == company.id
    assert user.name == "vinit sharma"
    assert user.email == "vinit.sharma@example.com"
    assert user.phone == "9999999999"
    assert user.role == UserRole.HR_ADMIN
    assert user.account_status == "PENDING_EMAIL_VERIFICATION"
    assert user.email_verification_token is not None
    assert user.is_active is False
    assert user.is_verified is False
    assert verify_password("SecurePassword@123456", user.password_hash)

    # 3. Verify Employee record was created
    employees = [obj for obj in added_objects if isinstance(obj, Employee)]
    assert len(employees) == 1
    employee = employees[0]
    assert employee.company_id == company.id
    assert employee.user_id == user.id
    assert employee.first_name == "vinit"
    assert employee.last_name == "sharma"
    assert employee.role == "hr_admin"
    assert employee.status == "ACTIVE"

    # 4. Verify Departments were created
    departments = [obj for obj in added_objects if isinstance(obj, Department)]
    assert len(departments) == 3
    dept_codes = {d.department_code for d in departments}
    assert dept_codes == {"MGMT", "ENG", "HR"}

    # 5. Verify Leave policies were created
    leave_policies = [obj for obj in added_objects if isinstance(obj, EmployeeLeavePolicy)]
    assert len(leave_policies) == 2
    leave_types = {lp.leave_type for lp in leave_policies}
    assert leave_types == {"Sick Leave", "Casual Leave"}

    # 6. Verify OTP was created
    mock_repo.create_otp.assert_awaited_once()
    otp_call_args = mock_repo.create_otp.call_args.kwargs
    assert otp_call_args["user_id"] == user.id
    assert otp_call_args["purpose"] == "email_verification"

    # 7. Verify email was sent
    mock_email_svc.send_verification_email.assert_awaited_once()

    # 8. Verify commit and refresh were called
    mock_session.commit.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio(loop_scope="session")
async def test_auth_service_duplicate_email_returns_409():
    """Test duplicate verified email raises ConflictException (409)."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_existing_user = MagicMock(spec=User)
    mock_existing_user.is_verified = True
    mock_repo.get_user_by_email.return_value = mock_existing_user

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    payload = RegisterRequest.model_validate({
        "name": "Vinit Sharma",
        "email": "existing@example.com",
        "phone": "9999999999",
        "password": "Password@123",
        "company_name": "EquinoxSphere",
    })

    with pytest.raises(ConflictException) as exc_info:
        await service.register_user(payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "Email already exists."
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="session")
async def test_auth_service_duplicate_phone_returns_409():
    """Test duplicate verified phone raises ConflictException (409)."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_repo.get_user_by_email.return_value = None
    mock_existing_phone_user = MagicMock(spec=User)
    mock_existing_phone_user.is_verified = True
    mock_repo.get_user_by_phone.return_value = mock_existing_phone_user

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    payload = RegisterRequest.model_validate({
        "name": "Vinit Sharma",
        "email": "newemail@example.com",
        "phone": "9999999999",
        "password": "Password@123",
        "company_name": "EquinoxSphere",
    })

    with pytest.raises(ConflictException) as exc_info:
        await service.register_user(payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "Phone already exists."


@pytest.mark.asyncio(loop_scope="session")
async def test_auth_service_transaction_rollback_on_db_error():
    """Test that when a database error occurs, rollback is performed and DatabaseException is raised."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    mock_repo.get_user_by_email.return_value = None
    mock_repo.get_user_by_phone.return_value = None

    from sqlalchemy.exc import SQLAlchemyError
    mock_session.flush.side_effect = SQLAlchemyError("Connection reset")

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    payload = RegisterRequest.model_validate({
        "name": "Vinit Sharma",
        "email": "rollback@example.com",
        "phone": "9999999999",
        "password": "Password@123",
        "company_name": "EquinoxSphere",
    })

    with pytest.raises(DatabaseException):
        await service.register_user(payload)

    mock_session.rollback.assert_awaited_once()


# ============================================================================
# 3. Response Schema Serialization Tests
# ============================================================================

def test_register_response_serialization():
    """Test RegisterResponse envelope matches standard schema without leaking sensitive data."""
    response = RegisterResponse(
        success=True,
        message="Registration successful. Welcome to HRMS!",
        data=None,
        errors=None,
    )
    dumped = response.model_dump()
    assert dumped == {
        "success": True,
        "message": "Registration successful. Welcome to HRMS!",
        "data": None,
        "errors": None,
    }
    assert "password" not in str(dumped)
    assert "password_hash" not in str(dumped)


# ============================================================================
# 4. FastAPI HTTP Router Integration Tests
# ============================================================================

from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.services.auth_service import get_auth_service


@pytest.mark.asyncio(loop_scope="session")
async def test_fastapi_register_endpoint_success():
    """Test POST /api/v1/auth/register through FastAPI routing and dependency injection."""
    app = create_app()

    mock_auth_svc = AsyncMock()
    mock_auth_svc.register_user.return_value = None

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "first_name": "vinit",
            "last_name": "sharma",
            "name": "vinit sharma",
            "full_name": "vinit sharma",
            "company_name": "EquinoxSphere",
            "email": "sharma.vinit@example.com",
            "password": "SecurePassword@123",
            "phone": "9999999999",
        }
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert "Registration successful" in data["message"]
        assert data["data"] is None
        assert data["errors"] is None

    app.dependency_overrides.clear()


@pytest.mark.asyncio(loop_scope="session")
async def test_fastapi_register_endpoint_conflict():
    """Test POST /api/v1/auth/register returns 409 when AuthService raises ConflictException."""
    app = create_app()

    mock_auth_svc = AsyncMock()
    mock_auth_svc.register_user.side_effect = ConflictException(
        message="Email already exists.",
        errors=[{"field": "email", "message": "Email already exists."}],
    )

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "name": "Vinit Sharma",
            "company_name": "EquinoxSphere",
            "email": "existing@example.com",
            "password": "SecurePassword@123",
            "phone": "9999999999",
        }
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 409
        data = resp.json()
        assert data["success"] is False
        assert data["message"] == "Email already exists."
        assert data["errors"] == [{"field": "email", "message": "Email already exists."}]

    app.dependency_overrides.clear()

