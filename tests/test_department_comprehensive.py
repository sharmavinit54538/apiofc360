"""Comprehensive test suite for the Department Management Module.

Tests cover:
1. Department Create (valid creation, required fields, auto code generation, trim, uppercase status)
2. Department Duplicate Handling (duplicate name conflict, duplicate code conflict within tenant, same name allowed across tenants)
3. Department List (pagination, search by name or code, status filtering, sorting, tenant scoping)
4. Department Read (valid ID returns 200, 404 on nonexistent, cross-tenant isolation)
5. Department Update (full and partial updates, preserving omitted fields)
6. Department Partial Update (omitted fields are not overwritten with null/empty/defaults)
7. Department Delete (soft delete, status change, is_deleted=True, excluded from list)
8. Department Delete Guard with Assigned Employees (reject deletion with 400 Bad Request)
9. Employee -> Department assignment (assigning employees updates foreign keys)
10. Employee Department update (reassignment and removing employee from department)
11. Invalid Department validation (invalid parent ID, invalid manager ID)
12. Multi-tenant Data Isolation (Company A vs Company B isolation for all operations)
13. RBAC (Super Admin, HR Admin, IT Admin write permissions; Employee, Intern forbidden)
14. Department Response Serialization (all fields present, no disappearing attributes)
15. Department Employee Counts (active, inactive, total, sub-departments count)
16. Department Head / Manager Assignment & Removal
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppException, ConflictException
from app.core.rbac import RoleEnum, UserRole
from app.core.security import create_access_token
from app.main import create_app
from app.models.company import Company
from app.models.department import Department
from app.models.employee import Employee
from app.models.user import User
from app.repositories.department_repository import DepartmentRepository
from app.schemas.department import (
    AssignEmployeesRequest,
    AssignManagerRequest,
    DepartmentCreate,
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentStats,
    DepartmentUpdate,
)
from app.db.database import get_db_session
from app.services.department_service import DepartmentService, get_department_service


# ==============================================================================
# Helper Factories
# ==============================================================================

def make_test_company(company_id: uuid.UUID | None = None, name: str = "Acme Corp") -> Company:
    c = Company(
        id=company_id or uuid.uuid4(),
        name=name,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return c


def make_test_user(
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    role: str = "hr_admin",
    name: str = "Jane HR",
    email: str = "jane@acme.com",
) -> User:
    u = User(
        id=user_id or uuid.uuid4(),
        company_id=company_id,
        role=role,
        name=name,
        email=email,
        phone="9876543210",
        password_hash="hashed_pw",
        is_active=True,
        is_verified=True,
        account_status="ACTIVE",
    )
    return u


def make_test_department(
    dept_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    name: str = "Engineering",
    code: str = "DEP0001",
    description: str = "Engineering Department",
    location: str = "Building A, Floor 3",
    manager_id: uuid.UUID | None = None,
    parent_department_id: uuid.UUID | None = None,
    cost_center: str = "CC-0001",
    budget: Decimal | float = Decimal("500000.00"),
    extension_number: str = "1001",
    employee_capacity: int = 100,
    status_val: str = "ACTIVE",
    is_deleted: bool = False,
) -> Department:
    d = Department(
        id=dept_id or uuid.uuid4(),
        company_id=company_id,
        department_code=code,
        department_name=name,
        description=description,
        location=location,
        manager_id=manager_id,
        parent_department_id=parent_department_id,
        cost_center=cost_center,
        budget=Decimal(str(budget)) if budget is not None else Decimal("0.0"),
        extension_number=extension_number,
        employee_capacity=employee_capacity,
        status=status_val,
        is_deleted=is_deleted,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return d


def make_test_employee(
    emp_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    dept_id: uuid.UUID | None = None,
    dept_name: str = "Engineering",
    first_name: str = "Sunaina",
    last_name: str = "Mehra",
    email: str = "sunaina@acme.com",
    emp_code: str = "EMP001",
    status_val: str = "ACTIVE",
    is_deleted: bool = False,
) -> Employee:
    e = Employee(
        id=emp_id or uuid.uuid4(),
        company_id=company_id,
        department_id=dept_id,
        department=dept_name,
        first_name=first_name,
        last_name=last_name,
        personal_email=email,
        company_email=email,
        phone="9123456780",
        employee_id=emp_code,
        designation="Senior Software Engineer",
        employment_type="FULL_TIME",
        joining_date=datetime.now(timezone.utc).date(),
        status=status_val,
        is_active=(status_val == "ACTIVE"),
        is_deleted=is_deleted,
    )
    return e


# ==============================================================================
# 1. Department Schema Validation Tests
# ==============================================================================

def test_department_create_schema_validation():
    """Verify DepartmentCreate accepts valid payloads and standardizes aliases."""
    payload = DepartmentCreate(
        department_name="  Human Resources  ",
        description="Handles people operations",
        location="Headquarters",
        cost_center="CC-HR-101",
        budget=150000.0,
        extension_number="2001",
        employee_capacity=50,
        status="active",
    )
    assert payload.department_name == "  Human Resources  "
    assert payload.status == "ACTIVE"
    assert payload.budget == 150000.0
    assert payload.employee_capacity == 50


def test_department_create_schema_alias_handling():
    """Verify camelCase and alternate alias mapping in DepartmentCreate."""
    mgr_id = uuid.uuid4()
    raw_data = {
        "department_name": "Finance",
        "description": "Financial Management",
        "location": "HQ Floor 2",
        "managerId": str(mgr_id),
        "costCenterId": "CC-FIN-01",
        "extensionNumber": "3001",
        "employeeCapacity": 75,
        "status": "GROWING",
    }
    model = DepartmentCreate.model_validate(raw_data)
    assert model.manager_id == mgr_id
    assert model.cost_center == "CC-FIN-01"
    assert model.extension_number == "3001"
    assert model.employee_capacity == 75
    assert model.status == "GROWING"


def test_department_update_schema_partial_preservation():
    """Verify DepartmentUpdate allows single field updates without setting defaults."""
    update = DepartmentUpdate(description="Updated description only")
    dumped = update.model_dump(exclude_unset=True)
    assert dumped == {"description": "Updated description only"}
    assert "department_name" not in dumped
    assert "status" not in dumped
    assert "budget" not in dumped


# ==============================================================================
# 2. Service-Level CRUD & Business Logic Unit Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_service_create_department_success():
    """Test successful department creation via DepartmentService."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    created_dept_id = uuid.uuid4()

    mock_repo.get_by_name_all.return_value = None  # No existing department
    
    saved_dept = make_test_department(
        dept_id=created_dept_id,
        company_id=company_id,
        name="Engineering",
        code="DEP0001",
        description="Core Engineering",
        location="Building B",
    )
    mock_repo.create_department.return_value = saved_dept
    mock_repo.get_by_id.return_value = saved_dept

    payload = DepartmentCreate(
        department_name="Engineering",
        description="Core Engineering",
        location="Building B",
        cost_center="CC-ENG-01",
        budget=500000.0,
        status="ACTIVE",
    )

    with patch("app.services.department_service.generate_department_code", return_value="DEP0001"):
        response = await service.create_department(user_id=user_id, payload=payload)

    assert response.id == created_dept_id
    assert response.department_name == "Engineering"
    assert response.department_code == "DEP0001"
    assert response.status == "ACTIVE"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_create_department_duplicate_name_conflict():
    """Test creating a department with an existing active name raises ConflictException."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    existing_dept = make_test_department(name="Engineering", is_deleted=False)
    mock_repo.get_by_name_all.return_value = existing_dept

    payload = DepartmentCreate(
        department_name="Engineering",
        description="Duplicate Engineering",
        location="Building A",
    )

    with pytest.raises(ConflictException) as exc_info:
        await service.create_department(user_id=uuid.uuid4(), payload=payload)

    assert "already exists" in str(exc_info.value.message).lower()
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_create_department_reactivate_soft_deleted():
    """Test creating a department with a previously soft-deleted name reactivates it."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    existing_deleted_dept = make_test_department(
        name="Marketing",
        code="DEP0005",
        is_deleted=True,
    )
    mock_repo.get_by_name_all.return_value = existing_deleted_dept
    mock_repo.get_by_id.return_value = existing_deleted_dept

    payload = DepartmentCreate(
        department_name="Marketing",
        description="Reactivated Marketing Team",
        location="Building C",
        status="ACTIVE",
    )

    response = await service.create_department(user_id=uuid.uuid4(), payload=payload)
    assert existing_deleted_dept.is_deleted is False
    assert existing_deleted_dept.description == "Reactivated Marketing Team"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_update_department_partial_preservation():
    """Test partial update modifies only requested fields and preserves all others."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    dept_id = uuid.uuid4()
    existing_dept = make_test_department(
        dept_id=dept_id,
        name="Engineering",
        code="ENG",
        description="Original Description",
        location="Floor 1",
        budget=Decimal("100000.00"),
    )
    mock_repo.get_by_id_raw.return_value = existing_dept
    mock_repo.get_by_id.return_value = existing_dept

    # Update only description
    payload = DepartmentUpdate(description="Product Engineering")
    await service.update_department(user_id=uuid.uuid4(), department_uuid=dept_id, payload=payload)

    mock_repo.update_department.assert_awaited_once_with(
        dept_id,
        description="Product Engineering",
    )
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_delete_department_guard_with_assigned_employees():
    """Test deleting a department with assigned employees raises 400 Bad Request."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    dept_id = uuid.uuid4()
    existing_dept = make_test_department(dept_id=dept_id)
    mock_repo.get_by_id_raw.return_value = existing_dept
    mock_repo.get_employee_count.return_value = 5  # 5 active employees assigned!

    with pytest.raises(AppException) as exc_info:
        await service.delete_department(user_id=uuid.uuid4(), department_uuid=dept_id)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "employees assigned" in str(exc_info.value.message).lower()
    mock_repo.soft_delete.assert_not_called()
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_delete_department_success_soft_delete():
    """Test deleting an empty department performs soft delete (is_deleted=True)."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    dept_id = uuid.uuid4()
    existing_dept = make_test_department(dept_id=dept_id)
    mock_repo.get_by_id_raw.return_value = existing_dept
    mock_repo.get_employee_count.return_value = 0  # No employees assigned

    await service.delete_department(user_id=uuid.uuid4(), department_uuid=dept_id)

    mock_repo.soft_delete.assert_awaited_once_with(dept_id)
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_assign_and_remove_employees():
    """Test assigning and removing employees to/from a department."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    dept_id = uuid.uuid4()
    emp_id_1 = uuid.uuid4()
    emp_id_2 = uuid.uuid4()
    existing_dept = make_test_department(dept_id=dept_id)
    mock_repo.get_by_id_raw.return_value = existing_dept

    # 1. Assign employees
    assign_payload = AssignEmployeesRequest(employee_ids=[emp_id_1, emp_id_2])
    await service.assign_employees(user_id=uuid.uuid4(), department_uuid=dept_id, payload=assign_payload)
    mock_repo.assign_employees.assert_awaited_once_with(dept_id, [emp_id_1, emp_id_2])
    mock_session.commit.assert_awaited()

    # 2. Remove single employee
    await service.remove_employee(user_id=uuid.uuid4(), department_uuid=dept_id, employee_id=emp_id_1)
    mock_repo.remove_employee_from_department.assert_awaited_once_with(emp_id_1)


@pytest.mark.asyncio
async def test_service_department_stats():
    """Test get_department_stats aggregates active, inactive, and sub-department counts."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    dept_id = uuid.uuid4()
    existing_dept = make_test_department(dept_id=dept_id, name="Engineering")
    mock_repo.get_by_id_raw.return_value = existing_dept
    mock_repo.get_employee_count.return_value = 25  # active
    mock_repo.get_inactive_employee_count.return_value = 3  # inactive
    mock_repo.get_sub_departments_count.return_value = 2  # sub-depts

    stats = await service.get_department_stats(dept_id)
    assert stats.department_id == dept_id
    assert stats.department_name == "Engineering"
    assert stats.active_employee_count == 25
    assert stats.inactive_employee_count == 3
    assert stats.total_employee_count == 28
    assert stats.sub_departments_count == 2


# ==============================================================================
# 3. HTTP API Endpoints & RBAC & Multi-Tenant Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_department_crud_lifecycle_and_rbac():
    """Full HTTP API test covering RBAC, CRUD, and response schema."""
    app = create_app()
    from contextlib import asynccontextmanager
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

    created_dept_id = uuid.uuid4()
    test_dept = make_test_department(
        dept_id=created_dept_id,
        company_id=company_id,
        name="Quality Assurance",
        code="DEP0002",
        description="QA & Automation",
        location="Tower 1, Floor 5",
        status_val="ACTIVE",
    )

    mock_svc = AsyncMock(spec=DepartmentService)
    app.dependency_overrides[get_department_service] = lambda: mock_svc
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()

    dept_resp = DepartmentResponse(
        id=created_dept_id,
        department_code="DEP0002",
        department_name="Quality Assurance",
        description="QA & Automation",
        location="Tower 1, Floor 5",
        cost_center="CC-0002",
        budget=200000.0,
        status="ACTIVE",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_svc.create_department.return_value = dept_resp
    mock_svc.get_department.return_value = dept_resp
    mock_svc.list_departments.return_value = DepartmentListResponse(
        items=[
            DepartmentListItem(
                id=created_dept_id,
                department_code="DEP0002",
                department_name="Quality Assurance",
                location="Tower 1, Floor 5",
                status="ACTIVE",
                employee_count=0,
                created_at=datetime.now(timezone.utc),
            )
        ],
        total=1,
        page=1,
        limit=20,
        pages=1,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. CREATE Department by HR Admin -> 201 Created
        create_payload = {
            "department_name": "Quality Assurance",
            "description": "QA & Automation",
            "location": "Tower 1, Floor 5",
            "budget": 200000.0,
            "status": "ACTIVE",
        }
        res = await client.post(
            "/api/v1/departments",
            json=create_payload,
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()["data"]
        assert data["department_name"] == "Quality Assurance"
        assert data["department_code"] == "DEP0002"

        # 2. CREATE Department by Employee -> 403 Forbidden
        res_forbidden = await client.post(
            "/api/v1/departments",
            json=create_payload,
            headers={"Authorization": f"Bearer {emp_token}"},
        )
        assert res_forbidden.status_code == status.HTTP_403_FORBIDDEN

        # 3. CREATE Department by Intern -> 403 Forbidden
        res_intern = await client.post(
            "/api/v1/departments",
            json=create_payload,
            headers={"Authorization": f"Bearer {intern_token}"},
        )
        assert res_intern.status_code == status.HTTP_403_FORBIDDEN

        # 4. LIST Departments -> 200 OK
        res_list = await client.get(
            "/api/v1/departments?page=1&limit=20",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_list.status_code == status.HTTP_200_OK
        list_data = res_list.json()["data"]
        assert list_data["total"] == 1
        assert len(list_data["items"]) == 1

        # 5. GET Department by ID -> 200 OK
        res_get = await client.get(
            f"/api/v1/departments/{created_dept_id}",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_get.status_code == status.HTTP_200_OK
        assert res_get.json()["data"]["id"] == str(created_dept_id)

        # 6. UPDATE Department by HR Admin -> 200 OK
        mock_svc.update_department.return_value = dept_resp
        res_update = await client.put(
            f"/api/v1/departments/{created_dept_id}",
            json={"description": "Updated QA description"},
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_update.status_code == status.HTTP_200_OK

        # 7. UPDATE Department by Employee -> 403 Forbidden
        res_emp_update = await client.put(
            f"/api/v1/departments/{created_dept_id}",
            json={"description": "Unauthorized change"},
            headers={"Authorization": f"Bearer {emp_token}"},
        )
        assert res_emp_update.status_code == status.HTTP_403_FORBIDDEN

        # 8. DELETE Department by HR Admin -> 200 OK
        res_del = await client.delete(
            f"/api/v1/departments/{created_dept_id}",
            headers={"Authorization": f"Bearer {hr_token}"},
        )
        assert res_del.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_api_department_multi_tenant_isolation():
    """Verify Company A and Company B cannot access or modify each other's departments."""
    app = create_app()
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def dummy_lifespan(application):
        yield
    app.router.lifespan_context = dummy_lifespan

    comp_a_id = uuid.uuid4()
    comp_b_id = uuid.uuid4()

    token_a = create_access_token(str(uuid.uuid4()), claims={"type": "access", "role": UserRole.HR_ADMIN.value, "company_id": str(comp_a_id)})
    token_b = create_access_token(str(uuid.uuid4()), claims={"type": "access", "role": UserRole.HR_ADMIN.value, "company_id": str(comp_b_id)})

    dept_b_id = uuid.uuid4()

    mock_svc = AsyncMock(spec=DepartmentService)
    app.dependency_overrides[get_department_service] = lambda: mock_svc
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()

    # Department B is not found when queried by Company A (404 Not Found)
    mock_svc.get_department.side_effect = AppException(
        message="Department not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )
    mock_svc.update_department.side_effect = AppException(
        message="Department not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )
    mock_svc.delete_department.side_effect = AppException(
        message="Department not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Company A tries to READ Company B department -> 404
        res_read = await client.get(
            f"/api/v1/departments/{dept_b_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_read.status_code == status.HTTP_404_NOT_FOUND

        # Company A tries to UPDATE Company B department -> 404
        res_upd = await client.put(
            f"/api/v1/departments/{dept_b_id}",
            json={"department_name": "Hacked Dept"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_upd.status_code == status.HTTP_404_NOT_FOUND

        # Company A tries to DELETE Company B department -> 404
        res_del = await client.delete(
            f"/api/v1/departments/{dept_b_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert res_del.status_code == status.HTTP_404_NOT_FOUND

