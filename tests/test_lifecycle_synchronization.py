"""Comprehensive test suite for Lifecycle Synchronization between User, Employee, and Manager models,
atomic deactivation workflows, session validation in auth middleware, and token service rotation.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import HTTPException

from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User, UserRole, UserAccountStatus
from app.models.refresh_token import RefreshToken
from app.core.exceptions import AppException
from app.middleware.auth import get_current_user, get_current_active_user, get_current_employee
from app.services.token_service import TokenService
from app.services.auth_service import AuthService
from app.services.employee_service import EmployeeService
from app.services.manager_service import ManagerService
from app.services.exit_service import ExitService
from app.schemas.employee.update import EmployeeUpdate
from app.schemas.manager import ManagerUpdate
from app.schemas.auth import LoginRequest


# ==============================================================================
# 1. Model is_deactivated Property Tests
# ==============================================================================

def test_employee_is_deactivated_property():
    """Verify Employee.is_deactivated computes correctly across various statuses."""
    emp = Employee(
        id=uuid.uuid4(),
        employee_id="EMP-001",
        first_name="Test",
        last_name="User",
        company_email="emp@example.com",
        is_active=True,
        is_deleted=False,
        status="ACTIVE",
        employment_status="ACTIVE",
    )
    assert emp.is_deactivated is False

    # Deactivated via is_active=False
    emp.is_active = False
    assert emp.is_deactivated is True

    # Deactivated via soft delete
    emp.is_active = True
    emp.is_deleted = True
    assert emp.is_deactivated is True

    # Deactivated via statuses
    emp.is_deleted = False
    for deact_status in ["DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED"]:
        emp.status = deact_status
        assert emp.is_deactivated is True

    # Deactivated via employment_status
    emp.status = "ACTIVE"
    for emp_status in ["EXITED", "TERMINATED"]:
        emp.employment_status = emp_status
        assert emp.is_deactivated is True


def test_manager_is_deactivated_property():
    """Verify Manager.is_deactivated computes correctly across various statuses."""
    mgr = Manager(
        id=uuid.uuid4(),
        manager_id="MGR-001",
        first_name="Test",
        last_name="Manager",
        company_email="mgr@example.com",
        is_active=True,
        is_deleted=False,
        status="ACTIVE",
    )
    assert mgr.is_deactivated is False

    # Deactivated via is_active=False
    mgr.is_active = False
    assert mgr.is_deactivated is True

    # Deactivated via soft delete
    mgr.is_active = True
    mgr.is_deleted = True
    assert mgr.is_deactivated is True

    # Deactivated via statuses
    mgr.is_deleted = False
    for deact_status in ["DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED"]:
        mgr.status = deact_status
        assert mgr.is_deactivated is True


# ==============================================================================
# 2. EmployeeService Atomic Deactivation and Synchronization
# ==============================================================================

@pytest.mark.asyncio
async def test_employee_service_deactivate_employee_syncs_user_and_revokes_tokens():
    """Verify deactivate_employee sets Employee.is_active=False, User.is_active=False, and revokes tokens."""
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

    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_emp = Employee(
        id=emp_id,
        user_id=user_id,
        company_id=company_id,
        employee_id="EMP-001",
        first_name="Jane",
        last_name="Doe",
        company_email="jane@example.com",
        role="employee",
        is_active=True,
        status="ACTIVE",
    )

    service._require_employee_in_company = AsyncMock(return_value=mock_emp)

    await service.deactivate_employee(
        admin_id=admin_id,
        company_id=company_id,
        employee_uuid=emp_id,
        reason="Resigned",
    )

    assert mock_emp.is_active is False
    assert mock_emp.status == "DISABLED"
    assert mock_emp.deactivated_by == admin_id
    assert mock_emp.deactivation_reason == "Resigned"
    assert mock_emp.deactivated_at is not None

    assert session.execute.call_count >= 1
    auth_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_employee_service_delete_employee_syncs_user():
    """Verify delete_employee soft-deletes employee, deactivates user, and revokes tokens."""
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

    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_emp = Employee(
        id=emp_id,
        user_id=user_id,
        company_id=company_id,
        employee_id="EMP-001",
        first_name="Jane",
        last_name="Doe",
        company_email="jane@example.com",
        role="employee",
        is_active=True,
        status="ACTIVE",
    )
    mock_user = User(
        id=user_id,
        name="Jane Doe",
        email="jane@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )

    service._require_employee_in_company = AsyncMock(return_value=mock_emp)
    mock_user_result = MagicMock()
    mock_user_result.scalar_one_or_none.return_value = mock_user
    session.execute = AsyncMock(return_value=mock_user_result)

    await service.delete_employee(
        admin_id=admin_id,
        company_id=company_id,
        employee_uuid=emp_id,
    )

    repo.soft_delete.assert_awaited_once_with(emp_id, deleted_by=admin_id)
    assert mock_user.is_active is False
    assert mock_user.account_status == "DEACTIVATED"
    assert mock_user.is_deleted is True
    auth_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id)
    session.commit.assert_awaited_once()


# ==============================================================================
# 3. ManagerService Atomic Deactivation and Synchronization
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_service_deactivate_manager_syncs_user_and_revokes_tokens():
    """Verify deactivate_manager sets Manager.is_active=False, User.is_active=False, and revokes tokens."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    email_service = AsyncMock()
    service = ManagerService(
        session=session,
        manager_repository=repo,
        auth_repository=auth_repo,
        email_service=email_service,
    )

    user_id = uuid.uuid4()
    mgr_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    mock_mgr = Manager(
        id=mgr_id,
        user_id=user_id,
        manager_id="MGR-001",
        first_name="Boss",
        last_name="Man",
        company_email="boss@example.com",
        role="manager",
        is_active=True,
        status="ACTIVE",
    )

    repo.get_by_id_raw = AsyncMock(return_value=mock_mgr)

    await service.deactivate_manager(
        admin_id=admin_id,
        manager_uuid=mgr_id,
    )

    assert mock_mgr.is_active is False
    assert mock_mgr.status == "DISABLED"
    assert mock_mgr.deactivated_by == admin_id
    assert mock_mgr.deactivated_at is not None

    repo.update_status.assert_awaited_once_with(mgr_id, "DISABLED")
    auth_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id)
    session.commit.assert_awaited_once()


# ==============================================================================
# 4. ExitService Complete Exit Lifecycle Synchronization
# ==============================================================================

@pytest.mark.asyncio
async def test_exit_service_complete_exit_syncs_all():
    """Verify complete_exit sets Employee status=ARCHIVED, employment_status=EXITED, is_active=False, User.is_active=False, and revokes tokens."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    emp_repo = AsyncMock()
    service = ExitService(
        session=session,
        repo=repo,
        auth_repo=auth_repo,
        employee_repo=emp_repo,
    )

    user_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    exit_id = uuid.uuid4()
    company_id = uuid.uuid4()

    mock_emp = Employee(
        id=emp_id,
        user_id=user_id,
        company_id=company_id,
        employee_id="EMP-001",
        first_name="Leaving",
        last_name="Employee",
        company_email="leaving@example.com",
        is_active=True,
        status="ACTIVE",
        employment_status="ACTIVE",
    )

    mock_exit = MagicMock()
    mock_exit.id = exit_id
    mock_exit.employee_id = emp_id
    mock_exit.company_id = company_id
    mock_exit.status = "APPROVED"
    mock_exit.reason = "Career Growth"
    mock_exit.comments = None
    mock_exit.personal_email = "leaving@example.com"
    mock_exit.personal_phone = "9876543210"
    mock_exit.manager_remarks = None
    mock_exit.hr_remarks = None
    mock_exit.last_working_date = datetime.now(timezone.utc).date()
    mock_exit.created_at = datetime.now(timezone.utc)
    mock_exit.updated_at = datetime.now(timezone.utc)
    mock_exit.employee = mock_emp

    repo.get_exit_by_id = AsyncMock(return_value=mock_exit)
    repo.get_kt_by_exit_id = AsyncMock(return_value=MagicMock(is_completed=True))
    repo.get_asset_returns_by_exit_id = AsyncMock(return_value=[])
    repo.get_clearance_by_exit_id = AsyncMock(return_value=MagicMock(overall_status="CLEARED"))
    repo.get_fnf_by_exit_id = AsyncMock(return_value=MagicMock(payment_status="PAID"))

    await service.complete_exit(
        exit_uuid=exit_id,
    )

    repo.update_exit_status.assert_awaited_once_with(exit_id, "COMPLETED")
    assert session.execute.call_count >= 1
    auth_repo.revoke_all_user_refresh_tokens.assert_awaited_once_with(user_id)
    session.commit.assert_awaited_once()


# ==============================================================================
# 5. Auth Middleware Session Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_get_current_user_rejects_inactive_user():
    """Verify get_current_user rejects inactive user with 403 Forbidden."""
    session = AsyncMock()
    user_id = uuid.uuid4()
    claims = {"sub": str(user_id)}

    mock_user = User(
        id=user_id,
        name="Inactive User",
        email="inactive@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=False,
        account_status="DEACTIVATED",
    )

    with patch("app.middleware.auth.AuthRepository") as MockAuthRepo:
        repo_inst = AsyncMock()
        repo_inst.get_user_by_id = AsyncMock(return_value=mock_user)
        MockAuthRepo.return_value = repo_inst

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(claims=claims, session=session)

        assert exc_info.value.status_code == 403
        assert "inactive or disabled" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_user_rejects_user_with_deactivated_employee_profile():
    """Verify get_current_user rejects active user if their linked Employee record is deactivated."""
    session = AsyncMock()
    user_id = uuid.uuid4()
    claims = {"sub": str(user_id)}

    mock_user = User(
        id=user_id,
        name="Deactivated Employee User",
        email="emp@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )
    mock_emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        employee_id="EMP-001",
        first_name="Emp",
        last_name="User",
        company_email="emp@example.com",
        is_active=False,
        status="DISABLED",
    )

    with patch("app.middleware.auth.AuthRepository") as MockAuthRepo:
        repo_inst = AsyncMock()
        repo_inst.get_user_by_id = AsyncMock(return_value=mock_user)
        MockAuthRepo.return_value = repo_inst

        emp_result = MagicMock()
        emp_result.scalar_one_or_none.return_value = mock_emp
        session.execute = AsyncMock(return_value=emp_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(claims=claims, session=session)

        assert exc_info.value.status_code == 403
        assert "Employee profile is inactive, deactivated, or terminated." in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_user_rejects_user_with_archived_exited_employee_profile():
    """Verify get_current_user rejects active user if their linked Employee record has employment_status=EXITED."""
    session = AsyncMock()
    user_id = uuid.uuid4()
    claims = {"sub": str(user_id)}

    mock_user = User(
        id=user_id,
        name="Exited Employee User",
        email="emp@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )
    mock_emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        employee_id="EMP-001",
        first_name="Emp",
        last_name="User",
        company_email="emp@example.com",
        is_active=True,
        status="ARCHIVED",
        employment_status="EXITED",
    )

    with patch("app.middleware.auth.AuthRepository") as MockAuthRepo:
        repo_inst = AsyncMock()
        repo_inst.get_user_by_id = AsyncMock(return_value=mock_user)
        MockAuthRepo.return_value = repo_inst

        emp_result = MagicMock()
        emp_result.scalar_one_or_none.return_value = mock_emp
        session.execute = AsyncMock(return_value=emp_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(claims=claims, session=session)

        assert exc_info.value.status_code == 403
        assert "Employee profile is inactive, deactivated, or terminated." in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_employee_rejects_deactivated_employee():
    """Verify get_current_employee rejects inactive/deactivated employee profile."""
    session = AsyncMock()
    user_id = uuid.uuid4()
    claims = {"sub": str(user_id)}

    mock_emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        employee_id="EMP-001",
        first_name="Emp",
        last_name="User",
        company_email="emp@example.com",
        is_active=False,
        status="DISABLED",
    )

    with patch("app.repositories.employee_repository.EmployeeRepository.get_by_user_id", new_callable=AsyncMock) as mock_get_by_user:
        mock_get_by_user.return_value = mock_emp

        with pytest.raises(HTTPException) as exc_info:
            await get_current_employee(claims=claims, session=session)

        assert exc_info.value.status_code == 403
        assert "Employee profile is inactive, deactivated, or terminated." in exc_info.value.detail


# ==============================================================================
# 6. TokenService Session Validation on Token Rotation
# ==============================================================================

@pytest.mark.asyncio
async def test_token_service_rotate_refresh_token_rejects_inactive_user():
    """Verify rotate_refresh_token rejects inactive user and revokes token."""
    session = AsyncMock()
    auth_repo = AsyncMock()
    token_svc = TokenService(session=session, auth_repository=auth_repo)

    user_id = uuid.uuid4()
    mock_user = User(
        id=user_id,
        name="Inactive User",
        email="inactive@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=False,
        account_status="DEACTIVATED",
    )
    token_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash="hash123",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        revoked=False,
    )
    token_record.user = mock_user

    auth_repo.get_refresh_token_by_hash = AsyncMock(return_value=token_record)

    with patch("app.services.token_service.decode_token", return_value={"sub": str(user_id), "type": "refresh"}):
        with pytest.raises(AppException) as exc_info:
            await token_svc.rotate_refresh_token(refresh_token="valid_token_string")

        assert exc_info.value.status_code == 401
        auth_repo.revoke_refresh_token.assert_awaited_once_with(token_record.id)


@pytest.mark.asyncio
async def test_token_service_rotate_refresh_token_rejects_deactivated_employee():
    """Verify rotate_refresh_token rejects token rotation if associated employee profile is deactivated."""
    session = AsyncMock()
    auth_repo = AsyncMock()
    token_svc = TokenService(session=session, auth_repository=auth_repo)

    user_id = uuid.uuid4()
    mock_user = User(
        id=user_id,
        name="User",
        email="emp@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=True,
        account_status="ACTIVE",
    )
    mock_emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        employee_id="EMP-001",
        first_name="Emp",
        last_name="User",
        company_email="emp@example.com",
        is_active=False,
        status="DISABLED",
    )
    token_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash="hash123",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        revoked=False,
    )
    token_record.user = mock_user

    auth_repo.get_refresh_token_by_hash = AsyncMock(return_value=token_record)

    emp_res = MagicMock()
    emp_res.scalar_one_or_none.return_value = mock_emp
    session.execute = AsyncMock(return_value=emp_res)

    with patch("app.services.token_service.decode_token", return_value={"sub": str(user_id), "type": "refresh"}):
        with pytest.raises(AppException) as exc_info:
            await token_svc.rotate_refresh_token(refresh_token="valid_token_string")

        assert exc_info.value.status_code == 401
        assert "User account or employment profile is inactive or terminated." in exc_info.value.message
        assert mock_user.is_active is False
        auth_repo.revoke_refresh_token.assert_awaited_once_with(token_record.id)


# ==============================================================================
# 7. AuthService Login Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_service_login_rejects_deactivated_employee():
    """Verify login is rejected with 403 if linked Employee profile is deactivated."""
    session = AsyncMock()
    auth_repo = AsyncMock()
    token_svc = AsyncMock()
    email_svc = AsyncMock()
    auth_svc = AuthService(
        session=session,
        auth_repository=auth_repo,
        token_service=token_svc,
        email_service=email_svc,
    )

    user_id = uuid.uuid4()
    mock_user = User(
        id=user_id,
        name="Emp User",
        email="emp@example.com",
        phone="9876543210",
        role=UserRole.EMPLOYEE,
        is_active=True,
        is_verified=True,
        account_status="ACTIVE",
    )
    mock_emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        employee_id="EMP-001",
        first_name="Emp",
        last_name="User",
        company_email="emp@example.com",
        is_active=False,
        status="DISABLED",
    )

    auth_repo.get_user_by_identifier = AsyncMock(return_value=mock_user)

    with patch("app.services.auth_service.verify_password", return_value=True):
        emp_res = MagicMock()
        emp_res.scalar_one_or_none.return_value = mock_emp
        session.execute = AsyncMock(return_value=emp_res)

        payload = LoginRequest(email="emp@example.com", password="Password123!")

        with pytest.raises(AppException) as exc_info:
            await auth_svc.login(payload=payload)

        assert exc_info.value.status_code == 403
        assert "Account or employment profile is inactive or terminated." in exc_info.value.message
        assert mock_user.is_active is False
        assert mock_user.account_status == "DEACTIVATED"
