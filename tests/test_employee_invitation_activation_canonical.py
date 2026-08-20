"""Comprehensive Canonical Test Suite for Employee Invitation and Activation Flow.

Covers:
1. Valid invitation token validation returns correct employee and company data without leaking secrets.
2. Invalid / non-existent token validation returns 400 Bad Request.
3. Empty / whitespace token validation returns 400 Bad Request.
4. Expired token validation (timezone-aware UTC) returns 400 Bad Request.
5. Already used / active employee token validation returns 400 Bad Request.
6. Successful employee activation sets password, links/activates user, updates status, and clears token.
7. Token reuse after activation is strictly prevented (returns 400).
8. Resend invitation invalidates previous token and makes new token valid.
9. Candidate conversion to employee persists matching activation_token in DB before generating activation email URL.
10. Route equivalence across all validate aliases.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
from fastapi import HTTPException

from app.core.exceptions import AppException
from app.models.employee import Employee
from app.models.user import User, UserRole
from app.models.company import Company
from app.schemas.employee import ActivateEmployeeRequest, ActivateOnboardingRequest
from app.services.employee_service import (
    EmployeeService,
    validate_employee_invitation_token,
    mask_token,
)
from app.api.onboarding import validate_onboarding_token, validate_onboarding_token_alias
from app.services.hr_admin_service import HRAdminService
from app.services.recruitment_service import RecruitmentService


# ─────────────────────────────────────────────────────────────────────────────
# 1. Helper Mask Token Test
# ─────────────────────────────────────────────────────────────────────────────

def test_mask_token_safe_logging():
    """Verify mask_token masks full secrets for logging."""
    assert mask_token("") == "N/A"
    assert mask_token(None) == "N/A"
    assert mask_token("abc") == "***"
    assert mask_token("12345678") == "***"
    assert mask_token("FjUB_long_secret_token_SYUQ") == "FjUB...SYUQ"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Canonical Validator Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_canonical_validate_success():
    """Verify that a valid token returns employee model and sanitized dict without leaking secrets."""
    session = AsyncMock()
    token = "valid_invitation_token_1234567890abcdef"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    emp_uuid = uuid.uuid4()
    comp_uuid = uuid.uuid4()

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=comp_uuid,
        employee_id="EMP-2026-001",
        first_name="Priya",
        last_name="Sharma",
        personal_email="priya@example.com",
        company_email="priya@ofc360.com",
        phone="9876543210",
        department="Engineering",
        designation="Software Engineer",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
        joining_date=date(2026, 9, 1),
    )

    mock_emp_result = MagicMock()
    mock_emp_result.scalar_one_or_none.return_value = mock_emp

    mock_comp_result = MagicMock()
    mock_comp_result.scalar_one_or_none.return_value = "Acme Global Technologies"

    session.execute.side_effect = [mock_emp_result, mock_comp_result]

    emp, data = await validate_employee_invitation_token(session, token)

    assert emp.id == emp_uuid
    assert data["valid"] is True
    assert data["employee_code"] == "EMP-2026-001"
    assert data["name"] == "Priya Sharma"
    assert data["personal_email"] == "priya@example.com"
    assert data["company_name"] == "Acme Global Technologies"
    assert data["department"] == "Engineering"

    # Verify no sensitive fields leaked in data
    assert "activation_token" not in data
    assert "password" not in data
    assert "password_hash" not in data
    assert "jwt_secret" not in data


@pytest.mark.asyncio
async def test_canonical_validate_empty_or_whitespace_token_raises_400():
    """Verify empty or whitespace token raises 400 Bad Request."""
    session = AsyncMock()

    with pytest.raises(AppException) as exc1:
        await validate_employee_invitation_token(session, "")
    assert exc1.value.status_code == 400
    assert "Invalid invitation token" in exc1.value.message

    with pytest.raises(AppException) as exc2:
        await validate_employee_invitation_token(session, "   ")
    assert exc2.value.status_code == 400


@pytest.mark.asyncio
async def test_canonical_validate_nonexistent_token_raises_400():
    """Verify non-existent token raises 400 Bad Request."""
    session = AsyncMock()
    mock_empty = MagicMock()
    mock_empty.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_empty

    with pytest.raises(AppException) as exc:
        await validate_employee_invitation_token(session, "non_existent_token_xyz")
    assert exc.value.status_code == 400
    assert "Invalid invitation token" in exc.value.message


@pytest.mark.asyncio
async def test_canonical_validate_expired_token_raises_400():
    """Verify expired token (UTC comparison) raises 400 Bad Request."""
    session = AsyncMock()
    token = "expired_token_12345"
    expired_time = datetime.now(timezone.utc) - timedelta(hours=2)

    mock_emp = Employee(
        id=uuid.uuid4(),
        employee_id="EMP-EXP-001",
        first_name="Ravi",
        last_name="Kumar",
        personal_email="ravi@example.com",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expired_time,
    )
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_emp
    session.execute.return_value = mock_res

    with pytest.raises(AppException) as exc:
        await validate_employee_invitation_token(session, token)
    assert exc.value.status_code == 400
    assert "expired" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_canonical_validate_already_used_token_raises_400():
    """Verify already activated employee raises 400 Bad Request."""
    session = AsyncMock()
    token = "used_token_12345"

    mock_emp = Employee(
        id=uuid.uuid4(),
        employee_id="EMP-USED-001",
        first_name="Anita",
        last_name="Roy",
        personal_email="anita@example.com",
        status="ACTIVE",
        user_id=uuid.uuid4(),
        is_active=True,
        is_deleted=False,
        activation_token=None,
        activation_token_expires_at=None,
    )
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_emp
    session.execute.return_value = mock_res

    with pytest.raises(AppException) as exc:
        await validate_employee_invitation_token(session, token)
    assert exc.value.status_code == 400
    assert "already" in exc.value.message.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Employee Activation & Invalidation Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_employee_full_flow():
    """Verify activating employee hashes password, creates/links user, sets status, and clears token."""
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

    emp_uuid = uuid.uuid4()
    comp_uuid = uuid.uuid4()
    token = "active_flow_token_xyz"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    mock_emp = Employee(
        id=emp_uuid,
        user_id=None,
        company_id=comp_uuid,
        employee_id="EMP-FLOW-001",
        first_name="Deepak",
        last_name="Verma",
        personal_email="deepak@example.com",
        company_email="deepak@ofc360.com",
        phone="9988776655",
        status="INVITED",
        role="EMPLOYEE",
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
        new_password="SuperSecretPassword@2026",
        confirm_password="SuperSecretPassword@2026",
    )

    await service.activate_employee(emp_uuid, payload)

    # 1. User creation and session add
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
    assert created_user.must_change_password is False
    assert created_user.password_hash != "SuperSecretPassword@2026"

    # 2. Token cleared and status updated on employee
    assert mock_emp.activation_token is None
    assert mock_emp.activation_token_expires_at is None
    assert mock_emp.status == "ONBOARDING_PENDING"
    assert session.commit.called


@pytest.mark.asyncio
async def test_activate_employee_token_reuse_prevented():
    """Verify that once activation_token is None, subsequent activation calls are rejected with 400."""
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

    emp_uuid = uuid.uuid4()
    mock_emp = Employee(
        id=emp_uuid,
        user_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        employee_id="EMP-USED-002",
        first_name="Rohan",
        last_name="Gupta",
        personal_email="rohan@example.com",
        status="ACTIVE",
        is_active=True,
        is_deleted=False,
        activation_token=None,
        activation_token_expires_at=None,
    )

    repo.get_by_id_raw.return_value = mock_emp

    payload = ActivateEmployeeRequest(
        token="some_old_token",
        new_password="NewPassword@2026",
        confirm_password="NewPassword@2026",
    )

    with pytest.raises(AppException) as exc:
        await service.activate_employee(emp_uuid, payload)
    assert exc.value.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 4. Resend Invitation Token Invalidation Test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hr_admin_resend_invitation_regenerates_and_persists_matching_token():
    """Verify HR Admin resend invitation replaces old token with new token in User, Employee, and email."""
    session = AsyncMock()
    email_service = AsyncMock()
    service = HRAdminService(session=session, email_service=email_service)

    admin_id = uuid.uuid4()
    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    old_token = "old_invitation_token_111"

    user = User(
        id=user_id,
        company_id=company_id,
        name="Sunil Joshi",
        email="sunil@example.com",
        account_status="INVITED",
        is_verified=False,
        email_verification_token=old_token,
    )
    emp = Employee(
        id=uuid.uuid4(),
        user_id=user_id,
        company_id=company_id,
        employee_id="EMP-RS-001",
        first_name="Sunil",
        last_name="Joshi",
        activation_token=old_token,
    )

    mock_user_res = MagicMock()
    mock_user_res.scalars.return_value.first.return_value = user

    mock_emp_res = MagicMock()
    mock_emp_res.scalars.return_value.first.return_value = emp

    mock_mgr_res = MagicMock()
    mock_mgr_res.scalars.return_value.first.return_value = None

    session.execute.side_effect = [mock_user_res, mock_emp_res, mock_mgr_res]

    await service.resend_invitation(company_id=company_id, admin_id=admin_id, target_user_id=user_id)

    # Verify new token was generated and persisted
    new_token = user.email_verification_token
    assert new_token != old_token
    assert emp.activation_token == new_token
    assert user.email_verification_expires_at is not None
    assert emp.activation_token_expires_at is not None
    assert session.commit.called

    # Verify email sent with the EXACT matching new token
    assert email_service.send_employee_onboarding_invite.called
    call_kwargs = email_service.send_employee_onboarding_invite.call_args[1]
    assert f"token={new_token}" in call_kwargs["activation_url"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Recruitment Candidate-to-Employee Token Persistence Test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recruitment_candidate_conversion_persists_matching_token():
    """Verify candidate conversion persists token in User & Employee before generating activation URL."""
    session = AsyncMock()
    repo = AsyncMock()
    auth_repo = AsyncMock()
    employee_repo = AsyncMock()
    email_service = AsyncMock()

    service = RecruitmentService(
        session=session,
        repo=repo,
        auth_repo=auth_repo,
        employee_repo=employee_repo,
        email_service=email_service,
    )

    app_id = uuid.uuid4()
    job_mock = MagicMock(department="Finance", designation="Analyst", employment_type="FULL_TIME")
    candidate_app = MagicMock(
        first_name="Neha",
        last_name="Kapoor",
        email="neha.candidate@example.com",
        phone="9876501234",
        status="OFFER_ACCEPTED",
        job=job_mock,
    )
    repo.get_application_by_id.return_value = candidate_app
    repo.get_latest_employee_seq.return_value = None
    repo.get_offer_by_application_id.return_value = None

    mock_res_id = MagicMock()
    mock_res_id.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_res_id

    created_user_mock = MagicMock(id=uuid.uuid4())
    auth_repo.create_user.return_value = created_user_mock

    created_emp_mock = MagicMock(id=uuid.uuid4())
    employee_repo.create_employee.return_value = created_emp_mock

    await service.convert_candidate_to_employee(
        user_id=uuid.uuid4(),
        app_uuid=app_id,
    )

    # Verify create_user received email_verification_token
    assert auth_repo.create_user.called
    user_kwargs = auth_repo.create_user.call_args[1]
    saved_token = user_kwargs["email_verification_token"]
    assert saved_token is not None
    assert len(saved_token) >= 32
    assert user_kwargs["email_verification_expires_at"] is not None

    # Verify create_employee received the SAME activation_token
    assert employee_repo.create_employee.called
    emp_kwargs = employee_repo.create_employee.call_args[1]
    assert emp_kwargs["activation_token"] == saved_token
    assert emp_kwargs["activation_token_expires_at"] == user_kwargs["email_verification_expires_at"]
    assert emp_kwargs["status"] == "INVITED"

    # Verify email was dispatched with matching token
    assert email_service.send_employee_activation_email.called
    email_kwargs = email_service.send_employee_activation_email.call_args[1]
    assert f"token={saved_token}" in email_kwargs["activation_url"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Route Alias Equivalence Test
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_onboarding_validate_alias_equivalence():
    """Verify /validate and /validate-token routes execute canonical token validation identically."""
    session = AsyncMock()
    token = "alias_test_token_12345"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    mock_emp = Employee(
        id=uuid.uuid4(),
        employee_id="EMP-ALIAS-001",
        first_name="Pooja",
        last_name="Nair",
        personal_email="pooja@example.com",
        status="INVITED",
        is_active=True,
        is_deleted=False,
        activation_token=token,
        activation_token_expires_at=expires_at,
    )

    mock_emp_res = MagicMock()
    mock_emp_res.scalar_one_or_none.return_value = mock_emp
    session.execute.return_value = mock_emp_res

    res1 = await validate_onboarding_token(token=token, session=session)
    session.execute.return_value = mock_emp_res
    res2 = await validate_onboarding_token_alias(token=token, session=session)

    assert res1.success is True
    assert res2.success is True
    assert res1.data["employee_code"] == res2.data["employee_code"] == "EMP-ALIAS-001"
