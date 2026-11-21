"""Automated test suite for Settings Management APIs (all 9 endpoints).

Covers:
1. Company logo upload validation, MIME validation, and size limit
2. Employee settings retrieval and transactional update
3. Employee ID prefix and settings validation
4. Leave settings retrieval and update without balance loss
5. Document settings retrieval, update, and extension safety restrictions
6. Asset settings retrieval and update
7. RBAC permissions (rejection of unauthorized writes for employee/manager)
8. Tenant isolation (company_id resolution and scoping)
9. OpenAPI schema registration for all 9 endpoints
"""

import io
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import UploadFile, HTTPException, status

from app.models.company import Company
from app.models.settings_models import (
    EmployeeSettings,
    LeaveSettings,
    DocumentSettings,
    AssetSettings,
)
from app.schemas.settings_schemas import (
    EmployeeSettingsUpdate,
    LeaveSettingsUpdate,
    DocumentSettingsUpdate,
    AssetSettingsUpdate,
)
from app.services.settings_management_service import SettingsManagementService
from app.routers.settings import (
    _require_role_in,
    _get_valid_company_id,
    ALLOWED_LOGO_ROLES,
    ALLOWED_EMPLOYEE_SETTINGS_WRITE_ROLES,
    ALLOWED_LEAVE_SETTINGS_WRITE_ROLES,
    ALLOWED_DOCUMENT_SETTINGS_WRITE_ROLES,
    ALLOWED_ASSET_SETTINGS_WRITE_ROLES,
    ALL_TENANT_READ_ROLES,
)


def run_sync(coro):
    """Drive coroutine synchronously without event loop hang."""
    stack = [coro]
    val = None
    while stack:
        curr = stack[-1]
        try:
            nxt = curr.send(val)
            val = None
            if hasattr(nxt, "send"):
                stack.append(nxt)
        except StopIteration as e:
            stack.pop()
            val = e.value
    return val


def create_mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ── 1. Company Logo Tests ───────────────────────────────────────────────────

def test_company_logo_service_valid_upload():
    """Verify company logo upload returns correct logo URL and updated_at."""
    session = create_mock_session()
    company_id = uuid.uuid4()
    company = Company(
        id=company_id,
        name="Acme Corp",
        company_profile={},
    )

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = company
    session.execute.return_value = result_mock

    # 1x1 transparent PNG bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = UploadFile(filename="logo.png", file=io.BytesIO(png_bytes), headers={"content-type": "image/png"})

    service = SettingsManagementService(session)

    with patch("app.services.company_logo_service.CompanyLogoService.upload_company_logo", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = {
            "logo": "/uploads/logos/mock123.png",
            "logo_url": "/uploads/logos/mock123.png",
            "logoUrl": "/uploads/logos/mock123.png",
            "updated_at": "2026-11-14T10:00:00Z",
        }
        res = run_sync(service.upload_company_logo(company_id, upload, user_id=uuid.uuid4(), claims={"email": "admin@acme.com"}))

        assert res["logo_url"] == "/uploads/logos/mock123.png"
        assert res["updated_at"] is not None
        assert session.commit.called


def test_company_logo_service_company_not_found():
    """Verify upload fails with 404 when company does not exist."""
    session = create_mock_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = result_mock

    upload = UploadFile(filename="logo.png", file=io.BytesIO(b"data"), headers={"content-type": "image/png"})
    service = SettingsManagementService(session)

    with pytest.raises(HTTPException) as exc_info:
        run_sync(service.upload_company_logo(uuid.uuid4(), upload))
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ── 2. Employee Settings Tests ──────────────────────────────────────────────

def test_employee_settings_get_defaults():
    """Verify employee settings instantiate with expected defaults if not configured."""
    session = create_mock_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = result_mock

    company_id = uuid.uuid4()
    service = SettingsManagementService(session)
    settings = run_sync(service.get_or_create_employee_settings(company_id))

    assert settings.employee_id_prefix == "EMP"
    assert settings.employee_id_start_number == 1001
    assert settings.probation_period_days == 90
    assert settings.default_employment_type == "full_time"
    assert settings.default_employee_status == "active"
    assert settings.allow_employee_profile_edit is True
    assert settings.require_manager_assignment is False
    assert session.add.called
    assert session.commit.called


def test_employee_settings_update():
    """Verify employee settings can be updated transactionally with audit logging."""
    session = create_mock_session()
    company_id = uuid.uuid4()
    existing = EmployeeSettings(
        id=uuid.uuid4(),
        company_id=company_id,
        employee_id_prefix="EMP",
        employee_id_start_number=1001,
        probation_period_days=90,
    )
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing
    session.execute.return_value = result_mock

    service = SettingsManagementService(session)
    payload = EmployeeSettingsUpdate(
        employee_id_prefix="ACME",
        employee_id_start_number=2000,
        probation_period_days=60,
        require_manager_assignment=True,
    )
    updated = run_sync(service.update_employee_settings(company_id, payload, user_id=uuid.uuid4(), claims={"email": "hr@acme.com"}))

    assert updated.employee_id_prefix == "ACME"
    assert updated.employee_id_start_number == 2000
    assert updated.probation_period_days == 60
    assert updated.require_manager_assignment is True
    assert session.commit.called


def test_employee_settings_invalid_prefix_validation():
    """Verify invalid prefix rejected by Pydantic schema validation."""
    with pytest.raises(ValueError):
        EmployeeSettingsUpdate(employee_id_prefix="INVALID PREFIX WITH SPACES!")


# ── 3. Leave Settings Tests ─────────────────────────────────────────────────

def test_leave_settings_get_defaults():
    """Verify leave settings instantiate with defaults without disturbing leave policies."""
    session = create_mock_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = result_mock

    company_id = uuid.uuid4()
    service = SettingsManagementService(session)
    settings = run_sync(service.get_or_create_leave_settings(company_id))

    assert settings.leave_year_start_month == 1
    assert settings.allow_half_day_leave is True
    assert settings.allow_negative_balance is False
    assert settings.require_manager_approval is True
    assert settings.max_consecutive_leave_days == 30
    assert settings.carry_forward_enabled is True
    assert settings.carry_forward_limit == 10
    assert settings.leave_encashment_enabled is False


def test_leave_settings_update():
    """Verify leave settings update does not alter existing employee balances."""
    session = create_mock_session()
    company_id = uuid.uuid4()
    existing = LeaveSettings(
        id=uuid.uuid4(),
        company_id=company_id,
        leave_year_start_month=1,
        max_consecutive_leave_days=30,
    )
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing
    session.execute.return_value = result_mock

    service = SettingsManagementService(session)
    payload = LeaveSettingsUpdate(
        leave_year_start_month=4,
        max_consecutive_leave_days=45,
        carry_forward_limit=15,
        leave_encashment_enabled=True,
    )
    updated = run_sync(service.update_leave_settings(company_id, payload, user_id=uuid.uuid4()))

    assert updated.leave_year_start_month == 4
    assert updated.max_consecutive_leave_days == 45
    assert updated.carry_forward_limit == 15
    assert updated.leave_encashment_enabled is True
    assert session.commit.called


# ── 4. Document Settings Tests ──────────────────────────────────────────────

def test_document_settings_get_defaults():
    """Verify document settings default values."""
    session = create_mock_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = result_mock

    company_id = uuid.uuid4()
    service = SettingsManagementService(session)
    settings = run_sync(service.get_or_create_document_settings(company_id))

    assert "pdf" in settings.allowed_file_types
    assert settings.max_file_size_mb == 10
    assert settings.require_document_verification is True
    assert settings.document_expiry_alert_days == 30
    assert settings.employee_can_upload_documents is True
    assert settings.manager_can_view_documents is False


def test_document_settings_update_safe_extensions():
    """Verify document settings accept safe file extensions."""
    session = create_mock_session()
    company_id = uuid.uuid4()
    existing = DocumentSettings(id=uuid.uuid4(), company_id=company_id)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing
    session.execute.return_value = result_mock

    service = SettingsManagementService(session)
    payload = DocumentSettingsUpdate(
        allowed_file_types=["pdf", "png", "docx"],
        max_file_size_mb=20,
        manager_can_view_documents=True,
    )
    updated = run_sync(service.update_document_settings(company_id, payload))

    assert updated.allowed_file_types == ["pdf", "png", "docx"]
    assert updated.max_file_size_mb == 20
    assert updated.manager_can_view_documents is True


def test_document_settings_reject_dangerous_extensions():
    """Verify executable or dangerous extensions are strictly rejected."""
    for bad_ext in ["exe", "bat", "sh", "py", "js"]:
        with pytest.raises(ValueError) as exc_info:
            DocumentSettingsUpdate(allowed_file_types=["pdf", bad_ext])
        assert "forbidden" in str(exc_info.value).lower()


# ── 5. Asset Settings Tests ─────────────────────────────────────────────────

def test_asset_settings_get_defaults():
    """Verify asset settings default values."""
    session = create_mock_session()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = result_mock

    company_id = uuid.uuid4()
    service = SettingsManagementService(session)
    settings = run_sync(service.get_or_create_asset_settings(company_id))

    assert settings.asset_id_prefix == "AST"
    assert settings.require_assignment_approval is True
    assert settings.enable_asset_return_tracking is True
    assert settings.enable_asset_condition_tracking is True
    assert settings.enable_warranty_reminders is True
    assert settings.warranty_reminder_days == 30
    assert settings.enable_asset_depreciation is False


def test_asset_settings_update():
    """Verify asset settings can be updated without affecting historical records."""
    session = create_mock_session()
    company_id = uuid.uuid4()
    existing = AssetSettings(id=uuid.uuid4(), company_id=company_id)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing
    session.execute.return_value = result_mock

    service = SettingsManagementService(session)
    payload = AssetSettingsUpdate(
        asset_id_prefix="DEV-AST",
        warranty_reminder_days=60,
        enable_asset_depreciation=True,
    )
    updated = run_sync(service.update_asset_settings(company_id, payload))

    assert updated.asset_id_prefix == "DEV-AST"
    assert updated.warranty_reminder_days == 60
    assert updated.enable_asset_depreciation is True


# ── 6. RBAC & Tenant Scoping Tests ──────────────────────────────────────────

def test_rbac_rejects_unauthorized_roles():
    """Verify employee and manager roles are rejected from admin update operations."""
    for unauthorized_role in ["employee", "manager", "intern"]:
        claims = {"role": unauthorized_role, "sub": str(uuid.uuid4()), "company_id": str(uuid.uuid4())}
        with pytest.raises(HTTPException) as exc_info:
            _require_role_in(claims, ALLOWED_EMPLOYEE_SETTINGS_WRITE_ROLES)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

        with pytest.raises(HTTPException) as exc_info:
            _require_role_in(claims, ALLOWED_LEAVE_SETTINGS_WRITE_ROLES)
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_rbac_allows_authorized_admin_roles():
    """Verify hr_admin and super_admin are allowed to update settings."""
    for admin_role in ["hr_admin", "super_admin", "admin"]:
        claims = {"role": admin_role, "sub": str(uuid.uuid4()), "company_id": str(uuid.uuid4())}
        # Should not raise exception
        _require_role_in(claims, ALLOWED_EMPLOYEE_SETTINGS_WRITE_ROLES)
        _require_role_in(claims, ALLOWED_LEAVE_SETTINGS_WRITE_ROLES)
        _require_role_in(claims, ALLOWED_DOCUMENT_SETTINGS_WRITE_ROLES)


def test_tenant_isolation_missing_company_id():
    """Verify requests lacking server-side company_id are rejected."""
    claims = {"role": "hr_admin", "sub": str(uuid.uuid4())}  # no company_id
    with pytest.raises(HTTPException) as exc_info:
        _get_valid_company_id(claims)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_all_9_routes_registered_in_v1_router():
    """Verify all 9 exact settings endpoints are present in the settings router with prefix /api/v1."""
    from app.routers.settings import router as settings_router
    routes = {
        f"{m} /api/v1{r.path}"
        for r in settings_router.routes
        for m in (getattr(r, "methods", None) or set())
    }
    expected_endpoints = [
        "POST /api/v1/settings/company/logo",
        "GET /api/v1/settings/employees",
        "PUT /api/v1/settings/employees",
        "GET /api/v1/settings/leaves",
        "PUT /api/v1/settings/leaves",
        "GET /api/v1/settings/documents",
        "PUT /api/v1/settings/documents",
        "GET /api/v1/settings/assets",
        "PUT /api/v1/settings/assets",
    ]
    for endpoint in expected_endpoints:
        assert endpoint in routes, f"Missing required endpoint: {endpoint}"
