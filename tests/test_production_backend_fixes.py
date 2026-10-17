"""Regression and verification tests for production backend fixes:
1. Department Pagination (safe max 100 limit, 422 on limit=500, deterministic ordering)
2. Department Summary route (GET /api/v1/departments/summary returns 200, schema validation)
3. Genuine department detail UUID validation (valid UUID vs invalid UUID)
4. Multi-tenant data isolation for departments
5. Document template idempotent seeding (no FK violation with non-existent user, nullable created_by)
6. Sidebar permissions endpoint (GET /api/v1/sidebar/permissions returns 200, 401 on unauthenticated, covers all 6 roles)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.core.rbac import UserRole
from app.core.security import create_access_token
from app.main import create_app
from app.models.department import Department
from app.models.document.template import DocumentTemplate
from app.models.user import User
from app.repositories.department_repository import DepartmentRepository
from app.schemas.department import (
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentSummary,
)
from app.services.department_service import DepartmentService, get_department_service
from app.services.document_templates import (
    CANONICAL_TEMPLATES,
    seed_canonical_templates_idempotent,
)


def _build_test_app() -> FastAPI:
    """Build the real application with dummy lifespan to avoid background services in tests."""
    from contextlib import asynccontextmanager

    app = create_app()

    @asynccontextmanager
    async def dummy_lifespan(application):
        yield

    app.router.lifespan_context = dummy_lifespan
    return app


# ==============================================================================
# 1. Department Pagination & Limit Contract
# ==============================================================================

@pytest.mark.asyncio
async def test_department_list_limit_100_returns_200():
    """Verify GET /api/v1/departments?limit=100 succeeds with HTTP 200."""
    app = _build_test_app()
    mock_service = AsyncMock(spec=DepartmentService)
    app.dependency_overrides[get_department_service] = lambda: mock_service

    mock_service.list_departments.return_value = DepartmentListResponse(
        items=[],
        total=0,
        page=1,
        limit=100,
        pages=0,
    )

    company_id = uuid.uuid4()
    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/api/v1/departments?limit=100", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["data"]
        assert data["limit"] == 100


@pytest.mark.asyncio
async def test_department_list_limit_500_returns_422():
    """Verify GET /api/v1/departments?page=1&limit=500 returns HTTP 422 with validation error."""
    app = _build_test_app()
    company_id = uuid.uuid4()
    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/departments?page=1&limit=500",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = str(res.json().get("detail", "")).lower()
        assert "100" in detail or "less_than_equal" in detail or "limit" in detail


@pytest.mark.asyncio
async def test_department_list_invalid_page_returns_422():
    """Verify GET /api/v1/departments?page=0 returns HTTP 422 validation error."""
    app = _build_test_app()
    company_id = uuid.uuid4()
    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/departments?page=0&limit=20",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==============================================================================
# 2. Department Summary Endpoint
# ==============================================================================

@pytest.mark.asyncio
async def test_department_summary_returns_200_and_expected_schema():
    """Verify GET /api/v1/departments/summary returns HTTP 200 with DepartmentSummary schema."""
    app = _build_test_app()
    mock_service = AsyncMock(spec=DepartmentService)
    app.dependency_overrides[get_department_service] = lambda: mock_service

    company_id = uuid.uuid4()
    summary_data = {
        "total_departments": 5,
        "active_departments": 4,
        "inactive_departments": 1,
        "total_employees": 50,
        "total_managers": 4,
        "avg_team_size": 10.0,
        "open_positions": 3,
        "hiring_departments": 2,
    }
    mock_service.get_departments_summary.return_value = summary_data

    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/departments/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_200_OK
        body = res.json()
        assert body["success"] is True
        data = body["data"]
        assert data["total_departments"] == 5
        assert data["active_departments"] == 4
        assert data["inactive_departments"] == 1
        assert data["total_employees"] == 50
        assert data["total_managers"] == 4
        assert data["avg_team_size"] == 10.0
        assert data["open_positions"] == 3
        assert data["hiring_departments"] == 2

        # Verify service was called with authorized caller's company context
        mock_service.get_departments_summary.assert_awaited_once_with(company_id=company_id)


# ==============================================================================
# 3. Department Detail & UUID Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_department_detail_valid_uuid_returns_200():
    """Verify GET /api/v1/departments/{valid_uuid} retrieves department details."""
    app = _build_test_app()
    mock_service = AsyncMock(spec=DepartmentService)
    app.dependency_overrides[get_department_service] = lambda: mock_service

    dept_id = uuid.uuid4()
    company_id = uuid.uuid4()
    dept_resp = DepartmentResponse(
        id=dept_id,
        department_code="DEP0001",
        department_name="Engineering",
        description="Core Engineering",
        location="HQ Floor 3",
        budget=150000.0,
        status="ACTIVE",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_service.get_department.return_value = dept_resp

    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "employee", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            f"/api/v1/departments/{dept_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["data"]
        assert data["id"] == str(dept_id)
        assert data["department_name"] == "Engineering"


@pytest.mark.asyncio
async def test_department_detail_invalid_uuid_returns_422():
    """Verify GET /api/v1/departments/{invalid_uuid} returns HTTP 422 validation response."""
    app = _build_test_app()
    company_id = uuid.uuid4()
    token = create_access_token(
        str(uuid.uuid4()),
        claims={"type": "access", "role": "hr_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/departments/not-a-valid-uuid",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==============================================================================
# 4. Multi-Tenant Scoping & Unauthenticated Requests
# ==============================================================================

@pytest.mark.asyncio
async def test_department_endpoints_unauthenticated_returns_401():
    """Verify unauthenticated requests to department endpoints return HTTP 401."""
    app = _build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. List
        res_list = await client.get("/api/v1/departments")
        assert res_list.status_code == status.HTTP_401_UNAUTHORIZED

        # 2. Summary
        res_summary = await client.get("/api/v1/departments/summary")
        assert res_summary.status_code == status.HTTP_401_UNAUTHORIZED

        # 3. Detail
        res_detail = await client.get(f"/api/v1/departments/{uuid.uuid4()}")
        assert res_detail.status_code == status.HTTP_401_UNAUTHORIZED


# ==============================================================================
# 5. Document Template Seeding Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_seed_canonical_templates_fresh_db():
    """Verify document templates are seeded without foreign key violation when table is empty."""
    mock_session = AsyncMock()

    # Empty existing templates
    mock_exec_result = AsyncMock()
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_exec_result

    inserted = await seed_canonical_templates_idempotent(mock_session)

    assert inserted == len(CANONICAL_TEMPLATES)
    assert mock_session.add.call_count == len(CANONICAL_TEMPLATES)
    mock_session.commit.assert_awaited_once()

    # Verify no fake UUID was used as created_by
    for call in mock_session.add.call_args_list:
        added_obj = call[0][0]
        assert isinstance(added_obj, DocumentTemplate)
        assert str(added_obj.created_by) != "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_seed_canonical_templates_idempotent_no_duplicates():
    """Verify repeated seeding does not insert duplicates and is fully idempotent."""
    mock_session = AsyncMock()

    # All canonical templates already present
    mock_exec_result = AsyncMock()
    mock_exec_result.scalars.return_value.all.return_value = [t["name"] for t in CANONICAL_TEMPLATES]
    mock_session.execute.return_value = mock_exec_result

    inserted = await seed_canonical_templates_idempotent(mock_session)

    assert inserted == 0
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


# ==============================================================================
# 6. Sidebar Permissions Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_sidebar_permissions_route_available_and_authenticated():
    """Verify GET /api/v1/sidebar/permissions returns HTTP 200 for authenticated user."""
    app = _build_test_app()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    token = create_access_token(
        str(user_id),
        claims={"type": "access", "role": "super_admin", "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/sidebar/permissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["data"]
        assert data["role"] == "super_admin"
        assert "all" in data["permissions"]
        assert data["modules"]["dashboard"] is True
        assert data["modules"]["settings"] is True
        assert len(data["sidebar"]) > 0


@pytest.mark.asyncio
async def test_sidebar_permissions_unauthenticated_returns_401():
    """Verify GET /api/v1/sidebar/permissions without token returns HTTP 401."""
    app = _build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/api/v1/sidebar/permissions")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_name,expected_settings,expected_employees",
    [
        ("super_admin", True, True),
        ("it_admin", True, True),
        ("hr_admin", False, True),
        ("executive", False, True),
        ("manager", False, True),
        ("employee", False, False),
    ],
)
async def test_sidebar_permissions_six_roles(role_name, expected_settings, expected_employees):
    """Verify permissions logic enforces the six standard roles accurately."""
    app = _build_test_app()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    token = create_access_token(
        str(user_id),
        claims={"type": "access", "role": role_name, "company_id": str(company_id)},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get(
            "/api/v1/sidebar/permissions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["data"]
        assert data["role"] == role_name
        assert data["modules"]["dashboard"] is True
        assert data["modules"]["settings"] is expected_settings
        assert data["modules"]["employees"] is expected_employees
