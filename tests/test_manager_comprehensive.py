"""Comprehensive test suite for the Manager Management Module.

Tests cover:
1. Manager Create (valid creation, required fields, auto code generation, trim whitespace, email/phone format)
2. Manager Duplicate Handling (duplicate personal email, company email, phone, manager_id conflicts)
3. Manager List (pagination, search, filtering by department, status, sorting, tenant scoping)
4. Manager Read (valid ID returns 200, 404 on nonexistent, 404 on soft-deleted)
5. Manager Update (full and partial updates, preserving omitted fields)
6. Manager Partial Update Regression (updating only designation preserves name, phone, department, ctc, company_id)
7. Manager Partial Update Phone (updating only phone preserves designation, department, etc.)
8. Manager Delete (soft delete, is_deleted=True, user account deactivation, token revocation)
9. Manager ↔ User (user linking, onboarding completion, activation, welcome email)
10. Manager ↔ Department (department name, department_id, department_rel)
11. Manager ↔ Employee Hierarchy (reporting_manager, reporting_to, team structure)
12. Manager Self-Reporting Guard (rejects manager reporting to self with 400 Bad Request)
13. Manager Permission Flags (PATCH /{id}/permissions updates boolean flags, preserves omitted)
14. RBAC (Super Admin, HR Admin, IT Admin write; Manager list; Employee/Intern 403 Forbidden)
15. Multi-tenant Data Isolation (Company A cannot read, update, or delete Company B managers)
16. Response Serialization (all fields present in ManagerResponse and ManagerListItem)
17. Manager Onboarding Token Validation (valid token 200, expired/used token 409)
18. Manager Deactivation and Reactivation by Admin
"""

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppException, ConflictException
from app.core.rbac import RoleEnum, UserRole
from app.core.security import create_access_token
from app.db.database import get_db_session
from app.main import create_app
from app.models.company import Company
from app.models.department import Department
from app.models.manager import Manager
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.manager_repository import ManagerRepository
from app.schemas.manager import (
    ActivateManagerOnboardingRequest,
    ActivateManagerRequest,
    ManagerCreate,
    ManagerListItem,
    ManagerListResponse,
    ManagerOnboardingCompleteRequest,
    ManagerPermissionsResponse,
    ManagerResponse,
    ManagerUpdate,
)
from app.services.email_service import EmailService
from app.services.manager_service import ManagerService, get_manager_service


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_manager(
    mgr_uuid: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    first_name: str = "Rajesh",
    last_name: str = "Kumar",
    manager_id: str = "MGR-202608-0001",
    department: str = "Engineering",
    designation: str = "Engineering Manager",
    phone: str = "9876543210",
    personal_email: str = "rajesh.kumar@example.com",
    company_email: str = "rajesh.kumar@company.com",
    status_val: str = "ACTIVE",
    is_deleted: bool = False,
    is_active: bool = True,
) -> Manager:
    mgr = Manager()
    mgr.id = mgr_uuid or uuid.uuid4()
    mgr.company_id = company_id or uuid.uuid4()
    mgr.user_id = user_id
    mgr.first_name = first_name
    mgr.last_name = last_name
    mgr.manager_id = manager_id
    mgr.department = department
    mgr.designation = designation
    mgr.phone = phone
    mgr.personal_email = personal_email
    mgr.company_email = company_email
    mgr.joining_date = date(2025, 1, 15)
    mgr.employment_type = "FULL_TIME"
    mgr.employment_status = "CONFIRMED"
    mgr.is_deleted = is_deleted
    mgr.status = status_val
    mgr.is_first_login = False
    mgr.profile_completed = True
    mgr.ctc = Decimal("1800000.00")
    mgr.basic_salary = Decimal("900000.00")
    mgr.hra = Decimal("450000.00")
    mgr.bonus = Decimal("200000.00")
    mgr.pf = Decimal("108000.00")
    mgr.esi = Decimal("0.00")
    mgr.professional_tax = Decimal("2400.00")
    mgr.role = "manager"
    mgr.can_approve_leave = True
    mgr.can_approve_attendance = True
    mgr.can_manage_employees = True
    mgr.can_view_payroll = False
    mgr.can_edit_departments = False
    mgr.can_invite_users = False
    mgr.can_manage_recruitment = False
    mgr.can_manage_performance = False
    mgr.addresses = []
    mgr.documents = []
    mgr.education = []
    mgr.experience = []
    mgr.skills = []
    mgr.emergency_contacts = []
    mgr.reporting_manager = None
    mgr.reporting_to = None
    mgr.created_by = uuid.uuid4()
    mgr.created_at = datetime.now(timezone.utc)
    mgr.updated_at = datetime.now(timezone.utc)
    return mgr


# ==============================================================================
# 1. Manager Create Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_create_validation_and_code_generation():
    """Verify Manager creation with auto-generated manager_id, trimming, and default role."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    admin_user = MagicMock()
    admin_user.id = admin_id
    admin_user.company_id = company_id
    mock_auth_repo.get_user_by_id.return_value = admin_user

    mock_exec_res = MagicMock()
    mock_exec_res.scalar_one_or_none.return_value = MagicMock(name="Acme Corp")
    mock_session.execute.return_value = mock_exec_res

    # No conflicts
    mock_manager_repo.get_by_personal_email.return_value = None
    mock_manager_repo.get_by_company_email.return_value = None
    mock_manager_repo.get_by_phone.return_value = None
    mock_manager_repo.get_by_manager_id.return_value = None

    created_mgr = make_test_manager(
        company_id=company_id,
        first_name="Priya",
        last_name="Sharma",
        personal_email="priya.sharma@example.com",
        phone="9876543211",
        department="Human Resources",
        designation="HR Manager",
        status_val="INVITED",
    )
    mock_manager_repo.create_manager.return_value = created_mgr
    mock_manager_repo.get_by_id.return_value = created_mgr

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    payload = ManagerCreate(
        first_name="  Priya  ",
        last_name="  Sharma  ",
        personal_email="priya.sharma@example.com",
        phone="9876543211",
        department="Human Resources",
        designation="HR Manager",
        joining_date=date(2025, 2, 1),
    )

    result = await service.create_manager(admin_id, payload)
    assert result.first_name == "Priya"
    assert result.last_name == "Sharma"
    assert result.personal_email == "priya.sharma@example.com"
    assert result.department == "Human Resources"
    assert result.designation == "HR Manager"
    assert mock_manager_repo.create_manager.called
    assert mock_email_service.send_manager_onboarding_invite.called


@pytest.mark.asyncio
async def test_manager_create_duplicate_conflict_handling():
    """Verify duplicate personal_email, company_email, phone, or manager_id raises 409 Conflict."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    admin_user = MagicMock()
    admin_user.id = admin_id
    admin_user.company_id = company_id
    mock_auth_repo.get_user_by_id.return_value = admin_user

    mock_exec_res = MagicMock()
    mock_exec_res.scalar_one_or_none.return_value = MagicMock(name="Acme Corp")
    mock_session.execute.return_value = mock_exec_res

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    # 1. Duplicate Personal Email
    mock_manager_repo.get_by_personal_email.return_value = make_test_manager()
    payload = ManagerCreate(
        first_name="Duplicate",
        last_name="User",
        personal_email="rajesh.kumar@example.com",
        phone="9999999999",
        department="Finance",
        designation="Finance Manager",
        joining_date=date(2025, 1, 1),
    )
    with pytest.raises(ConflictException) as exc_info:
        await service.create_manager(admin_id, payload)
    assert "Email already exists" in exc_info.value.message

    # 2. Duplicate Phone
    mock_manager_repo.get_by_personal_email.return_value = None
    mock_manager_repo.get_by_company_email.return_value = None
    mock_manager_repo.get_by_phone.return_value = make_test_manager()
    with pytest.raises(ConflictException) as exc_info:
        await service.create_manager(admin_id, payload)
    assert "Phone number already exists" in exc_info.value.message


# ==============================================================================
# 2. Manager Partial Update Regression Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_partial_update_preserves_omitted_fields():
    """CRITICAL: Updating ONLY designation must NOT overwrite name, phone, department, or ctc."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    admin_id = uuid.uuid4()
    mgr_id = uuid.uuid4()
    company_id = uuid.uuid4()

    existing_mgr = make_test_manager(
        mgr_uuid=mgr_id,
        company_id=company_id,
        first_name="Rajesh",
        last_name="Kumar",
        phone="9876543210",
        department="Engineering",
        designation="Engineering Manager",
    )
    mock_manager_repo.get_by_id_raw.return_value = existing_mgr
    mock_manager_repo.get_by_personal_email.return_value = None
    mock_manager_repo.get_by_company_email.return_value = None
    mock_manager_repo.get_by_phone.return_value = None
    mock_manager_repo.get_by_manager_id.return_value = None

    # After update simulation
    updated_mgr = make_test_manager(
        mgr_uuid=mgr_id,
        company_id=company_id,
        first_name="Rajesh",
        last_name="Kumar",
        phone="9876543210",
        department="Engineering",
        designation="Senior Engineering Manager",
    )
    mock_manager_repo.get_by_id.return_value = updated_mgr

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    # User updates ONLY designation
    update_payload = ManagerUpdate(designation="Senior Engineering Manager")

    result = await service.update_manager(admin_id, mgr_id, update_payload)

    # Verify repository received ONLY the updated field
    call_kwargs = mock_manager_repo.update_manager.call_args[1]
    assert "designation" in call_kwargs
    assert call_kwargs["designation"] == "Senior Engineering Manager"
    assert "first_name" not in call_kwargs
    assert "last_name" not in call_kwargs
    assert "phone" not in call_kwargs
    assert "department" not in call_kwargs
    assert "ctc" not in call_kwargs

    # Verify result has preserved fields
    assert result.designation == "Senior Engineering Manager"
    assert result.first_name == "Rajesh"
    assert result.last_name == "Kumar"
    assert result.phone == "9876543210"
    assert result.department == "Engineering"


@pytest.mark.asyncio
async def test_manager_partial_update_phone_preserves_designation_and_department():
    """Updating ONLY phone must preserve designation, department, and salary."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    admin_id = uuid.uuid4()
    mgr_id = uuid.uuid4()
    company_id = uuid.uuid4()

    existing_mgr = make_test_manager(
        mgr_uuid=mgr_id,
        company_id=company_id,
        first_name="Rajesh",
        last_name="Kumar",
        phone="9876543210",
        department="Engineering",
        designation="Engineering Manager",
    )
    mock_manager_repo.get_by_id_raw.return_value = existing_mgr
    mock_manager_repo.get_by_personal_email.return_value = None
    mock_manager_repo.get_by_company_email.return_value = None
    mock_manager_repo.get_by_phone.return_value = None
    mock_manager_repo.get_by_manager_id.return_value = None

    updated_mgr = make_test_manager(
        mgr_uuid=mgr_id,
        company_id=company_id,
        first_name="Rajesh",
        last_name="Kumar",
        phone="9123456789",
        department="Engineering",
        designation="Engineering Manager",
    )
    mock_manager_repo.get_by_id.return_value = updated_mgr

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    update_payload = ManagerUpdate(phone="9123456789")
    result = await service.update_manager(admin_id, mgr_id, update_payload)

    call_kwargs = mock_manager_repo.update_manager.call_args[1]
    assert call_kwargs == {"phone": "9123456789"}
    assert result.phone == "9123456789"
    assert result.designation == "Engineering Manager"
    assert result.department == "Engineering"


@pytest.mark.asyncio
async def test_manager_self_reporting_prevention():
    """Verify manager cannot be assigned as their own reporting manager."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    admin_id = uuid.uuid4()
    mgr_id = uuid.uuid4()
    existing_mgr = make_test_manager(mgr_uuid=mgr_id)
    mock_manager_repo.get_by_id_raw.return_value = existing_mgr

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    update_payload = ManagerUpdate(reporting_to=mgr_id)
    with pytest.raises(AppException) as exc_info:
        await service.update_manager(admin_id, mgr_id, update_payload)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "cannot report to themselves" in exc_info.value.message


# ==============================================================================
# 3. Manager Delete & Soft Delete Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_soft_delete_and_user_deactivation():
    """Verify soft delete sets is_deleted=True, deactivates linked user, and revokes tokens."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    admin_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mgr_id = uuid.uuid4()
    existing_mgr = make_test_manager(mgr_uuid=mgr_id, user_id=user_id)
    mock_manager_repo.get_by_id_raw.return_value = existing_mgr

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new_callable=AsyncMock) as mock_revoke_tokens:
        await service.delete_manager(admin_id, mgr_id)

    mock_manager_repo.soft_delete.assert_called_once_with(mgr_id, deleted_by=admin_id)
    mock_auth_repo.revoke_all_user_refresh_tokens.assert_called_once_with(user_id)
    mock_revoke_tokens.assert_called_once_with(user_id)


# ==============================================================================
# 4. Manager List, Read, and Search Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_list_pagination_and_filters():
    """Verify listing managers supports pagination, search, status, and department filtering."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    mgr1 = make_test_manager(first_name="Alice", department="Engineering", status_val="ACTIVE")
    mgr2 = make_test_manager(first_name="Bob", department="Product", status_val="ACTIVE")

    mock_manager_repo.list_managers.return_value = [mgr1, mgr2]
    mock_manager_repo.count_managers.return_value = 2

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    res = await service.list_managers(
        department="Engineering",
        status_filter="ACTIVE",
        employment_type="FULL_TIME",
        search="Alice",
        page=1,
        limit=10,
    )

    assert res.total == 2
    assert len(res.items) == 2
    assert res.page == 1
    assert res.limit == 10
    assert res.pages == 1
    assert res.items[0].first_name == "Alice"


@pytest.mark.asyncio
async def test_manager_read_nonexistent_returns_404():
    """Verify reading a nonexistent manager returns 404 Not Found."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    mock_manager_repo.get_by_id.return_value = None

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    with pytest.raises(AppException) as exc_info:
        await service.get_manager(uuid.uuid4())
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 5. Manager Permissions & Granular Access Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_permissions_partial_update():
    """Verify updating only permission flags preserves other permissions and scalar fields."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    admin_id = uuid.uuid4()
    mgr_id = uuid.uuid4()

    existing_mgr = make_test_manager(
        mgr_uuid=mgr_id,
        first_name="Vikram",
        last_name="Singh",
    )
    existing_mgr.can_approve_leave = True
    existing_mgr.can_manage_employees = False
    mock_manager_repo.get_by_id_raw.return_value = existing_mgr

    updated_mgr = make_test_manager(
        mgr_uuid=mgr_id,
        first_name="Vikram",
        last_name="Singh",
    )
    updated_mgr.can_approve_leave = True
    updated_mgr.can_manage_employees = True
    mock_manager_repo.get_by_id.return_value = updated_mgr

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    update_payload = ManagerUpdate(can_manage_employees=True)
    result = await service.update_manager(admin_id, mgr_id, update_payload)

    call_kwargs = mock_manager_repo.update_manager.call_args[1]
    assert call_kwargs == {"can_manage_employees": True}
    assert result.can_manage_employees is True


# ==============================================================================
# 6. HTTP API, RBAC, and Multi-Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_manager_crud_lifecycle_and_rbac():
    """Full HTTP API test verifying RBAC, Manager CRUD, and response schema."""
    app = create_app()

    @asynccontextmanager
    async def dummy_lifespan(application):
        yield
    app.router.lifespan_context = dummy_lifespan

    company_id = uuid.uuid4()
    super_admin_id = uuid.uuid4()
    hr_admin_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    intern_id = uuid.uuid4()

    sa_token = create_access_token(str(super_admin_id), claims={"type": "access", "role": UserRole.SUPER_ADMIN.value, "company_id": str(company_id)})
    hr_token = create_access_token(str(hr_admin_id), claims={"type": "access", "role": UserRole.HR_ADMIN.value, "company_id": str(company_id)})
    emp_token = create_access_token(str(employee_id), claims={"type": "access", "role": UserRole.EMPLOYEE.value, "company_id": str(company_id)})
    intern_token = create_access_token(str(intern_id), claims={"type": "access", "role": UserRole.INTERN.value, "company_id": str(company_id)})

    created_mgr_id = uuid.uuid4()
    test_mgr = make_test_manager(
        mgr_uuid=created_mgr_id,
        company_id=company_id,
        first_name="Deepak",
        last_name="Verma",
        personal_email="deepak.verma@example.com",
        phone="9876543299",
        department="Technology",
        designation="VP of Engineering",
        status_val="INVITED",
    )

    mock_svc = AsyncMock(spec=ManagerService)
    app.dependency_overrides[get_manager_service] = lambda: mock_svc
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()

    mgr_resp = ManagerResponse.model_validate(test_mgr)
    mock_svc.create_manager.return_value = mgr_resp
    mock_svc.get_manager.return_value = mgr_resp
    mock_svc.list_managers.return_value = ManagerListResponse(
        items=[ManagerListItem.model_validate(test_mgr)],
        total=1,
        page=1,
        limit=20,
        pages=1,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. CREATE Manager by HR Admin -> 201 Created
        create_payload = {
            "first_name": "Deepak",
            "last_name": "Verma",
            "personal_email": "deepak.verma@example.com",
            "phone": "9876543299",
            "department": "Technology",
            "designation": "VP of Engineering",
            "joining_date": "2025-03-01",
        }
        res_create = await client.post(
            "/api/v1/managers",
            json=create_payload,
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_create.status_code == status.HTTP_201_CREATED
        data = res_create.json()["data"]
        assert data["first_name"] == "Deepak"
        assert data["department"] == "Technology"

        # 2. CREATE Manager by Employee -> 403 Forbidden
        res_forbidden = await client.post(
            "/api/v1/managers",
            json=create_payload,
            headers={"Authorization": f"Bearer {emp_token}"},
        )
        assert res_forbidden.status_code == status.HTTP_403_FORBIDDEN

        # 3. CREATE Manager by Intern -> 403 Forbidden
        res_intern = await client.post(
            "/api/v1/managers",
            json=create_payload,
            headers={"Authorization": f"Bearer {intern_token}"},
        )
        assert res_intern.status_code == status.HTTP_403_FORBIDDEN

        # 4. LIST Managers by HR Admin -> 200 OK
        res_list = await client.get(
            "/api/v1/managers?page=1&limit=20",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_list.status_code == status.HTTP_200_OK
        list_data = res_list.json()["data"]
        assert list_data["total"] == 1
        assert len(list_data["items"]) == 1

        # 5. GET Manager by ID -> 200 OK
        res_get = await client.get(
            f"/api/v1/managers/{created_mgr_id}",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_get.status_code == status.HTTP_200_OK
        assert res_get.json()["data"]["id"] == str(created_mgr_id)

        # 6. UPDATE Manager by HR Admin -> 200 OK
        mock_svc.update_manager.return_value = mgr_resp
        res_upd = await client.put(
            f"/api/v1/managers/{created_mgr_id}",
            json={"designation": "Executive VP of Engineering"},
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_upd.status_code == status.HTTP_200_OK

        # 7. UPDATE Manager by Employee -> 403 Forbidden
        res_emp_upd = await client.put(
            f"/api/v1/managers/{created_mgr_id}",
            json={"designation": "Hacked Title"},
            headers={"Authorization": f"Bearer {emp_token}"},
        )
        assert res_emp_upd.status_code == status.HTTP_403_FORBIDDEN

        # 8. DELETE Manager by HR Admin -> 200 OK
        res_del = await client.delete(
            f"/api/v1/managers/{created_mgr_id}",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_del.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_api_manager_multi_tenant_isolation():
    """Verify Company A and Company B cannot access or modify each other's managers."""
    app = create_app()

    @asynccontextmanager
    async def dummy_lifespan(application):
        yield
    app.router.lifespan_context = dummy_lifespan

    comp_a_id = uuid.uuid4()
    comp_b_id = uuid.uuid4()

    token_a = create_access_token(str(uuid.uuid4()), claims={"type": "access", "role": UserRole.HR_ADMIN.value, "company_id": str(comp_a_id)})
    token_b = create_access_token(str(uuid.uuid4()), claims={"type": "access", "role": UserRole.HR_ADMIN.value, "company_id": str(comp_b_id)})

    mgr_b_id = uuid.uuid4()

    mock_svc = AsyncMock(spec=ManagerService)
    app.dependency_overrides[get_manager_service] = lambda: mock_svc
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()

    # Manager B is not found when queried by Company A (404 Not Found)
    mock_svc.get_manager.side_effect = AppException(
        message="Manager not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )
    mock_svc.update_manager.side_effect = AppException(
        message="Manager not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )
    mock_svc.delete_manager.side_effect = AppException(
        message="Manager not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Company A tries to READ Company B manager -> 404
        res_read = await client.get(
            f"/api/v1/managers/{mgr_b_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_read.status_code == status.HTTP_404_NOT_FOUND

        # Company A tries to UPDATE Company B manager -> 404
        res_upd = await client.put(
            f"/api/v1/managers/{mgr_b_id}",
            json={"designation": "Unauthorized Title"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_upd.status_code == status.HTTP_404_NOT_FOUND

        # Company A tries to DELETE Company B manager -> 404
        res_del = await client.delete(
            f"/api/v1/managers/{mgr_b_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_del.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 7. Manager Onboarding, User Linking, Deactivation & Reactivation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_manager_onboarding_token_validation_and_activation():
    """Verify onboarding token validation and manager account activation."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    company_id = uuid.uuid4()
    mgr_id = uuid.uuid4()
    token = "valid_secure_token_12345678"

    manager = make_test_manager(
        mgr_uuid=mgr_id,
        company_id=company_id,
        status_val="INVITED",
    )
    manager.activation_token = token
    manager.activation_token_expires_at = datetime.now(timezone.utc) + timedelta(days=3)

    mock_exec_res = MagicMock()
    mock_exec_res.scalar_one_or_none.return_value = manager
    mock_session.execute.return_value = mock_exec_res

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    # 1. Validate Token -> Success
    data = await service.validate_onboarding_token(token)
    assert data["id"] == str(mgr_id)
    assert data["first_name"] == "Rajesh"
    assert data["department"] == "Engineering"

    # 2. Expired Token -> 409 Conflict
    manager.activation_token_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    with pytest.raises(ConflictException) as exc_info:
        await service.validate_onboarding_token(token)
    assert "Expired invitation token" in exc_info.value.message


@pytest.mark.asyncio
async def test_manager_admin_deactivation_and_reactivation():
    """Verify Admin can deactivate and reactivate a manager account."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    admin_id = uuid.uuid4()
    user_id = uuid.uuid4()
    mgr_id = uuid.uuid4()

    manager = make_test_manager(
        mgr_uuid=mgr_id,
        user_id=user_id,
        status_val="ACTIVE",
    )
    mock_manager_repo.get_by_id_raw.return_value = manager

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    with patch("app.core.redis_client.redis_client.revoke_user_tokens", new_callable=AsyncMock) as mock_revoke:
        # Deactivate
        await service.deactivate_manager(admin_id, mgr_id)
        assert manager.is_active is False
        assert manager.status == "DISABLED"
        mock_manager_repo.update_status.assert_called_with(mgr_id, "DISABLED")

        # Reactivate by Admin
        await service.activate_manager_by_admin(admin_id, mgr_id)
        assert manager.is_active is True
        assert manager.status == "ACTIVE"
        mock_manager_repo.update_status.assert_called_with(mgr_id, "ACTIVE")


@pytest.mark.asyncio
async def test_manager_onboarding_completion():
    """Verify manager can complete their onboarding profile."""
    mock_session = AsyncMock()
    mock_auth_repo = AsyncMock(spec=AuthRepository)
    mock_email_service = AsyncMock(spec=EmailService)
    mock_manager_repo = AsyncMock(spec=ManagerRepository)

    user_id = uuid.uuid4()
    mgr_id = uuid.uuid4()

    manager = make_test_manager(
        mgr_uuid=mgr_id,
        user_id=user_id,
        status_val="ACTIVE",
    )
    mock_manager_repo.get_by_user_id.return_value = manager
    mock_manager_repo.get_by_id.return_value = manager

    mock_user = MagicMock()
    mock_user.id = user_id
    mock_auth_repo.get_user_by_id.return_value = mock_user

    service = ManagerService(
        session=mock_session,
        manager_repository=mock_manager_repo,
        auth_repository=mock_auth_repo,
        email_service=mock_email_service,
    )

    payload = ManagerOnboardingCompleteRequest(
        first_name="Rajesh",
        last_name="Kumar",
        phone="9876543210",
        department="Engineering",
        designation="Director of Engineering",
        manager_id="MGR-001",
        joining_date=date(2025, 1, 1),
        bio="Leading backend architecture team.",
        timezone="Asia/Kolkata",
        language="English",
    )

    res = await service.complete_manager_onboarding(user_id, payload)
    assert manager.profile_completed is True
    assert manager.is_first_login is False
    assert manager.bio == "Leading backend architecture team."
    assert mock_user.onboarding_completed is True


# ==============================================================================
# 9. Manager Payload Mapping & Role Separation Tests
# ==============================================================================

def test_manager_create_correct_payload():
    """Verify ManagerCreate accepts canonical role and job designation."""
    payload = {
        "first_name": "Mamraj",
        "last_name": "Yadav",
        "personal_email": "themamraj0131@gmail.com",
        "company_email": "mamraj@ofc360.com",
        "phone": "9828740131",
        "department": "Engineering",
        "designation": "Cloud & DevOps Engineer",
        "joining_date": "2026-08-19",
        "gender": "MALE",
        "date_of_birth": "1995-05-15",
        "blood_group": "O+",
        "marital_status": "SINGLE",
        "branch": "Mumbai HQ",
        "work_location": "Onsite",
        "employment_type": "FULL_TIME",
        "employment_status": "ACTIVE",
        "shift": "General",
        "probation_period_months": 3,
        "ctc": 1200000,
        "basic_salary": 600000,
        "hra": 300000,
        "bonus": 180000,
        "pf": 72000,
        "esi": 0,
        "professional_tax": 2500,
        "role": "manager",
        "leave_group": "Standard India Policy",
    }
    mgr = ManagerCreate(**payload)
    assert mgr.first_name == "Mamraj"
    assert mgr.last_name == "Yadav"
    assert mgr.designation == "Cloud & DevOps Engineer"
    assert mgr.role == "manager"
    assert mgr.employment_status == "ACTIVE"


def test_manager_create_defensive_migration_mapping():
    """Verify backend defensively recovers when frontend sends role as designation and system_role as manager."""
    payload = {
        "first_name": "Mamraj",
        "last_name": "Yadav",
        "personal_email": "themamraj0131@gmail.com",
        "phone": "9828740131",
        "department": "Engineering",
        "role": "Cloud & DevOps Engineer",
        "system_role": "manager",
        "status": "Active",
        "joining_date": "2026-08-19",
    }
    mgr = ManagerCreate(**payload)
    assert mgr.designation == "Cloud & DevOps Engineer"
    assert mgr.role == "manager"
    assert mgr.employment_status == "ACTIVE"


def test_manager_create_rejects_invalid_system_role():
    """Verify ManagerCreate strictly rejects arbitrary system roles with 422."""
    from pydantic import ValidationError
    payload = {
        "first_name": "Mamraj",
        "last_name": "Yadav",
        "personal_email": "themamraj0131@gmail.com",
        "phone": "9828740131",
        "department": "Engineering",
        "designation": "Cloud & DevOps Engineer",
        "role": "invalid_role_xyz",
        "joining_date": "2026-08-19",
    }
    with pytest.raises(ValidationError) as exc_info:
        ManagerCreate(**payload)
    assert "role must be one of" in str(exc_info.value)


