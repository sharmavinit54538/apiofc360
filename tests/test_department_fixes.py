"""Targeted tests for Department module fixes.

Verifies:
(a) Sub-department with no own head whose parent has a head returns 200 on GET /departments/{id}
(b) Two companies can each create a department with the same name without a 500
(c) List only returns the caller's company departments
(d) GET /departments/summary returns 200 and not 422
(e) List without a token returns 401
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.api.departments import router as departments_router
from app.core.rbac import UserRole
from app.core.security import create_access_token
from app.models.department import Department
from app.models.user import User
from app.repositories.department_repository import DepartmentRepository
from app.schemas.department import (
    DepartmentCreate,
    DepartmentListItem,
    DepartmentListResponse,
)
from app.services.department_service import DepartmentService, get_department_service


def _build_test_app() -> FastAPI:
    """Build a minimal test application mounting the department router."""
    app = FastAPI()
    app.include_router(departments_router)
    app.include_router(departments_router, prefix="/api/v1")
    return app


def _make_dept(
    dept_id: uuid.UUID,
    name: str,
    company_id: uuid.UUID,
    code: str = "DEP0001",
    parent_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    manager_user: User | None = None,
) -> Department:
    dept = Department(
        id=dept_id,
        department_name=name,
        department_code=code,
        company_id=company_id,
        description="Department description",
        location="Floor 1",
        parent_department_id=parent_id,
        manager_id=manager_id,
        status="ACTIVE",
        budget=Decimal("100000.00"),
        employee_capacity=50,
        is_deleted=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    if manager_user:
        dept.manager_user = manager_user
    return dept


# ==============================================================================
# (a) Sub-department with no own head whose parent has a head returns 200
# ==============================================================================

@pytest.mark.asyncio
async def test_sub_department_with_parent_head_returns_200():
    """Verify GET /departments/{id} returns 200 and resolves parent head without MissingGreenlet."""
    company_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    sub_dept_id = uuid.uuid4()
    parent_manager_id = uuid.uuid4()

    parent_manager = User(
        id=parent_manager_id,
        company_id=company_id,
        name="Sarah Connor",
        email="sarah@corp.com",
        phone="1234567890",
        password_hash="!",
        is_active=True,
        is_verified=True,
        role=UserRole.MANAGER,
    )
    parent_dept = _make_dept(
        dept_id=parent_id,
        name="Engineering",
        company_id=company_id,
        code="DEP0001",
        manager_id=parent_manager_id,
        manager_user=parent_manager,
    )
    sub_dept = _make_dept(
        dept_id=sub_dept_id,
        name="Quality Assurance",
        company_id=company_id,
        code="DEP0002",
        parent_id=parent_id,
        manager_id=None,
    )

    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)

    async def mock_get_by_id(uid, company_id=None):
        if uid == sub_dept_id:
            return sub_dept
        if uid == parent_id:
            return parent_dept
        return None

    mock_repo.get_by_id.side_effect = mock_get_by_id

    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    # 1. Test directly in DepartmentService (ensures no lazy load MissingGreenlet crash)
    response = await service.get_department(sub_dept_id, company_id=company_id)
    assert response.id == sub_dept_id
    assert response.department_name == "Quality Assurance"
    assert response.parent_department_name == "Engineering"
    assert response.reporting_manager_id == parent_manager_id
    assert response.reporting_manager_name == "Sarah Connor"

    # 2. Test via HTTP route GET /departments/{id}
    app = _build_test_app()
    app.dependency_overrides[get_department_service] = lambda: service

    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "super_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            f"/departments/{sub_dept_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["data"]
        assert data["id"] == str(sub_dept_id)
        assert data["reporting_manager_name"] == "Sarah Connor"


# ==============================================================================
# (b) Two companies can each create a department with the same name without 500
# ==============================================================================

@pytest.mark.asyncio
async def test_two_companies_can_create_department_with_same_name():
    """Verify multi-tenant isolation: different companies can reuse the same department name."""
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    dept_name = "Human Resources"

    mock_session = AsyncMock()
    mock_repo = AsyncMock(spec=DepartmentRepository)
    service = DepartmentService(session=mock_session, department_repository=mock_repo)

    dept_a_id = uuid.uuid4()
    dept_b_id = uuid.uuid4()

    dept_a = _make_dept(dept_a_id, dept_name, company_a, code="DEP0001")
    dept_b = _make_dept(dept_b_id, dept_name, company_b, code="DEP0001")

    # Name check returns None when queried with each company's ID
    mock_repo.get_by_name_all.return_value = None
    mock_repo.get_by_id_raw.return_value = None
    mock_repo.get_manager_by_user_id.return_value = None

    payload = DepartmentCreate(
        department_name=dept_name,
        description="HR Department",
        location="Headquarters",
        status="ACTIVE",
    )

    # Create in Company A
    mock_repo.create_department.return_value = dept_a
    mock_repo.get_by_id.return_value = dept_a
    with patch("app.services.department_service.generate_department_code", return_value="DEP0001"):
        res_a = await service.create_department(uuid.uuid4(), payload, company_id=company_a)
    assert res_a.department_name == dept_name

    # Create in Company B with the same department name
    mock_repo.create_department.return_value = dept_b
    mock_repo.get_by_id.return_value = dept_b
    with patch("app.services.department_service.generate_department_code", return_value="DEP0001"):
        res_b = await service.create_department(uuid.uuid4(), payload, company_id=company_b)
    assert res_b.department_name == dept_name

    # Ensure get_by_name_all was queried per company scope
    assert mock_repo.get_by_name_all.call_count == 2
    mock_repo.get_by_name_all.assert_any_call(dept_name, company_id=company_a)
    mock_repo.get_by_name_all.assert_any_call(dept_name, company_id=company_b)


# ==============================================================================
# (c) List only returns the caller's company departments
# ==============================================================================

@pytest.mark.asyncio
async def test_list_departments_scopes_to_callers_company():
    """Verify list_departments only returns departments for the authenticated caller's company."""
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()

    mock_service = AsyncMock(spec=DepartmentService)
    app = _build_test_app()
    app.dependency_overrides[get_department_service] = lambda: mock_service

    token_a = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_a)},
    )
    token_b = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_b)},
    )

    dept_a_item = DepartmentListItem(
        id=uuid.uuid4(),
        department_code="DEP0001",
        department_name="Company A Dept",
        location="Location A",
        status="ACTIVE",
        employee_count=5,
        created_at=datetime.now(timezone.utc),
    )
    dept_b_item = DepartmentListItem(
        id=uuid.uuid4(),
        department_code="DEP0002",
        department_name="Company B Dept",
        location="Location B",
        status="ACTIVE",
        employee_count=10,
        created_at=datetime.now(timezone.utc),
    )

    async def mock_list(company_id=None, **kwargs):
        if company_id == company_a:
            return DepartmentListResponse(items=[dept_a_item], total=1, page=1, limit=20, pages=1)
        if company_id == company_b:
            return DepartmentListResponse(items=[dept_b_item], total=1, page=1, limit=20, pages=1)
        return DepartmentListResponse(items=[], total=0, page=1, limit=20, pages=0)

    mock_service.list_departments.side_effect = mock_list

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Request with Company A's token
        res_a = await client.get("/departments", headers={"Authorization": f"Bearer {token_a}"})
        assert res_a.status_code == status.HTTP_200_OK
        data_a = res_a.json()["data"]
        assert data_a["total"] == 1
        assert data_a["items"][0]["department_name"] == "Company A Dept"

        # Request with Company B's token
        res_b = await client.get("/departments", headers={"Authorization": f"Bearer {token_b}"})
        assert res_b.status_code == status.HTTP_200_OK
        data_b = res_b.json()["data"]
        assert data_b["total"] == 1
        assert data_b["items"][0]["department_name"] == "Company B Dept"


# ==============================================================================
# (d) GET /departments/summary returns 200 and not 422
# ==============================================================================

@pytest.mark.asyncio
async def test_get_departments_summary_returns_200_not_422():
    """Verify GET /departments/summary is matched before /{id} and returns 200 without validation error."""
    company_id = uuid.uuid4()
    mock_service = AsyncMock(spec=DepartmentService)
    app = _build_test_app()
    app.dependency_overrides[get_department_service] = lambda: mock_service

    mock_service.get_departments_summary.return_value = {
        "total_departments": 4,
        "active_departments": 3,
        "inactive_departments": 1,
        "total_employees": 42,
        "total_managers": 3,
        "avg_team_size": 10.5,
        "open_positions": 0,
        "hiring_departments": 1,
    }

    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/departments/summary", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        assert body["success"] is True
        data = body["data"]
        assert data["total_departments"] == 4
        assert data["active_departments"] == 3
        assert data["inactive_departments"] == 1
        assert data["total_employees"] == 42
        assert data["total_managers"] == 3
        assert data["avg_team_size"] == 10.5
        assert data["open_positions"] == 0
        assert data["hiring_departments"] == 1

        # Also verify prefix /api/v1/departments/summary
        res_v1 = await client.get("/api/v1/departments/summary", headers={"Authorization": f"Bearer {token}"})
        assert res_v1.status_code == status.HTTP_200_OK


# ==============================================================================
# (e) List without a token returns 401
# ==============================================================================

@pytest.mark.asyncio
async def test_list_departments_without_token_returns_401():
    """Verify GET /departments rejects unauthenticated requests with 401 Unauthorized."""
    app = _build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/departments")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
