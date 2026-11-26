"""Settings router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, UploadFile, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.settings import (
    CompanyConfigSectionUpdate,
    DesignationCreateRequest,
    EmploymentTypeCreateRequest,
    HolidayCreateRequest,
)
from app.schemas.settings_schemas import (
    EmployeeSettingsUpdate,
    LeaveSettingsUpdate,
    DocumentSettingsUpdate,
    AssetSettingsUpdate,
)
from app.services.core_modules.settings_service import SettingsService
from app.services.settings_management_service import SettingsManagementService

# ── Role Permissions ──────────────────────────────────────────────────────────
ALLOWED_LOGO_ROLES = {
    "super_admin", "hr_admin", "admin", "company_admin", "it_admin",
    "executive", "ceo", "cto", "cfo", "coo", "hr_manager",
}
ALLOWED_EMPLOYEE_SETTINGS_WRITE_ROLES = {
    "super_admin", "hr_admin", "admin", "company_admin", "hr_manager",
}
ALLOWED_LEAVE_SETTINGS_WRITE_ROLES = {
    "super_admin", "hr_admin", "admin", "company_admin", "hr_manager",
}
ALLOWED_DOCUMENT_SETTINGS_WRITE_ROLES = {
    "super_admin", "hr_admin", "admin", "company_admin", "it_admin", "hr_manager",
}
ALLOWED_ASSET_SETTINGS_WRITE_ROLES = {
    "super_admin", "it_admin", "admin", "company_admin", "hr_admin",
}
ALL_TENANT_READ_ROLES = {
    "super_admin", "hr_admin", "admin", "company_admin", "it_admin",
    "executive", "ceo", "cto", "cfo", "coo", "manager", "employee", "intern", "hr_manager",
}


def _get_role(claims: dict) -> str:
    role = str(claims.get("role") or "").lower().strip()
    try:
        from app.models.user.role import RoleEnum
        return RoleEnum.from_str(role).value
    except Exception:
        return role


def _require_role_in(claims: dict, allowed_roles: set[str], error_msg: str = "Insufficient permissions.") -> None:
    role = str(claims.get("role") or "").lower().strip()
    norm = _get_role(claims)
    if role not in allowed_roles and norm not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)


def _get_valid_company_id(claims: dict) -> uuid.UUID:
    cid = claims.get("company_id")
    if not cid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No company association found in authentication claims.",
        )
    try:
        return uuid.UUID(str(cid))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid company identifier format.",
        )


def _get_uid(claims: dict) -> Optional[uuid.UUID]:
    uid = claims.get("sub")
    if not uid:
        return None
    try:
        return uuid.UUID(str(uid))
    except (ValueError, TypeError):
        return None


def _settings_response(data: Dict[str, Any], message: str) -> Dict[str, Any]:
    out = dict(data)
    out["success"] = True
    out["message"] = message
    out["data"] = data
    return out

router = APIRouter(prefix="/settings", tags=["Core - Settings"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/")
async def get_settings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.get_all_settings(cid)
    return _ok(res)


@router.put("/")
async def update_settings(
    payload: CompanyConfigSectionUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.update_settings_section(cid, "general", payload)
    return _ok(res)


@router.get("/company")
@router.get("/attendance")
@router.get("/leave")
@router.get("/payroll")
@router.get("/security")
@router.get("/workflow")
async def get_settings_section(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.get_all_settings(cid)
    return _ok(res)


@router.put("/company")
@router.put("/attendance")
@router.put("/leave")
@router.put("/payroll")
@router.put("/security")
@router.put("/workflow")
async def update_settings_section_endpoint(
    payload: CompanyConfigSectionUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.update_settings_section(cid, "section", payload)
    return _ok(res)


# ── Master Data: Employment Types ──────────────────────────────────────────

@router.get("/employment-types")
async def list_employment_types(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    items = await srv.list_employment_types(cid)
    return _ok(items)


@router.post("/employment-types")
async def create_employment_type(
    payload: EmploymentTypeCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.create_employment_type(cid, payload)
    return _ok({"id": str(res.id), "name": res.name, "code": res.code})


# ── Master Data: Designations ──────────────────────────────────────────────

@router.get("/designations")
async def list_designations(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    items = await srv.list_designations(cid)
    return _ok(items)


@router.post("/designations")
async def create_designation(
    payload: DesignationCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.create_designation(cid, payload)
    return _ok(res)


# ── Master Data: Holidays ──────────────────────────────────────────────────

@router.get("/holidays")
async def list_holidays(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    items = await srv.list_holidays(cid)
    return _ok(items)


@router.post("/holidays")
async def create_holiday(
    payload: HolidayCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.create_holiday(cid, payload)
    return _ok({"id": str(res.id), "name": res.name, "holiday_date": res.holiday_date.isoformat()})


# ── Enterprise Settings Management APIs (9 Target Endpoints) ───────────────

@router.post(
    "/company/logo",
    status_code=status.HTTP_200_OK,
    summary="Upload or update company logo",
    responses={
        status.HTTP_200_OK: {"description": "Company logo uploaded successfully."},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid file or unsupported format."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Authentication required."},
        status.HTTP_403_FORBIDDEN: {"description": "Insufficient permissions."},
        status.HTTP_404_NOT_FOUND: {"description": "Company not found."},
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: {"description": "File exceeds size limit."},
    },
)
async def upload_company_logo(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    file: UploadFile | None = File(None),
    logo: UploadFile | None = File(None),
) -> Dict[str, Any]:
    """Upload corporate logo for the authenticated organization."""
    _require_role_in(
        claims,
        ALLOWED_LOGO_ROLES,
        error_msg="Access denied: You do not have permission to update company logo.",
    )
    cid = _get_valid_company_id(claims)
    uid = _get_uid(claims)
    upload_file = file or logo
    if not upload_file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No image file provided. Please provide an image using field 'file' or 'logo'.",
        )
    srv = SettingsManagementService(session)
    result = await srv.upload_company_logo(cid, upload_file, user_id=uid, claims=claims)
    return _settings_response(result, "Company logo uploaded successfully.")


@router.get(
    "/employees",
    status_code=status.HTTP_200_OK,
    summary="Retrieve employee configuration",
)
async def get_employee_settings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve organization-wide employee configuration."""
    _require_role_in(claims, ALL_TENANT_READ_ROLES)
    cid = _get_valid_company_id(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.get_or_create_employee_settings(cid)
    data = {
        "employee_id_prefix": settings_obj.employee_id_prefix,
        "employee_id_start_number": settings_obj.employee_id_start_number,
        "probation_period_days": settings_obj.probation_period_days,
        "default_employment_type": settings_obj.default_employment_type,
        "default_employee_status": settings_obj.default_employee_status,
        "allow_employee_profile_edit": settings_obj.allow_employee_profile_edit,
        "require_manager_assignment": settings_obj.require_manager_assignment,
    }
    return _settings_response(data, "Employee settings retrieved successfully.")


@router.put(
    "/employees",
    status_code=status.HTTP_200_OK,
    summary="Update employee configuration",
)
async def update_employee_settings(
    payload: EmployeeSettingsUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update organization-wide employee configuration."""
    _require_role_in(
        claims,
        ALLOWED_EMPLOYEE_SETTINGS_WRITE_ROLES,
        error_msg="Access denied: Only HR or authorized administrators can update employee settings.",
    )
    cid = _get_valid_company_id(claims)
    uid = _get_uid(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.update_employee_settings(cid, payload, user_id=uid, claims=claims)
    data = {
        "employee_id_prefix": settings_obj.employee_id_prefix,
        "employee_id_start_number": settings_obj.employee_id_start_number,
        "probation_period_days": settings_obj.probation_period_days,
        "default_employment_type": settings_obj.default_employment_type,
        "default_employee_status": settings_obj.default_employee_status,
        "allow_employee_profile_edit": settings_obj.allow_employee_profile_edit,
        "require_manager_assignment": settings_obj.require_manager_assignment,
    }
    return _settings_response(data, "Employee settings updated successfully.")


@router.get(
    "/leaves",
    status_code=status.HTTP_200_OK,
    summary="Retrieve leave configuration",
)
async def get_leave_settings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve organization-wide leave management configuration."""
    _require_role_in(claims, ALL_TENANT_READ_ROLES)
    cid = _get_valid_company_id(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.get_or_create_leave_settings(cid)
    data = {
        "leave_year_start_month": settings_obj.leave_year_start_month,
        "allow_half_day_leave": settings_obj.allow_half_day_leave,
        "allow_negative_balance": settings_obj.allow_negative_balance,
        "require_manager_approval": settings_obj.require_manager_approval,
        "max_consecutive_leave_days": settings_obj.max_consecutive_leave_days,
        "carry_forward_enabled": settings_obj.carry_forward_enabled,
        "carry_forward_limit": settings_obj.carry_forward_limit,
        "leave_encashment_enabled": settings_obj.leave_encashment_enabled,
    }
    return _settings_response(data, "Leave settings retrieved successfully.")


@router.put(
    "/leaves",
    status_code=status.HTTP_200_OK,
    summary="Update leave configuration",
)
async def update_leave_settings(
    payload: LeaveSettingsUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update organization-wide leave management configuration."""
    _require_role_in(
        claims,
        ALLOWED_LEAVE_SETTINGS_WRITE_ROLES,
        error_msg="Access denied: Only HR or authorized administrators can update leave configuration.",
    )
    cid = _get_valid_company_id(claims)
    uid = _get_uid(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.update_leave_settings(cid, payload, user_id=uid, claims=claims)
    data = {
        "leave_year_start_month": settings_obj.leave_year_start_month,
        "allow_half_day_leave": settings_obj.allow_half_day_leave,
        "allow_negative_balance": settings_obj.allow_negative_balance,
        "require_manager_approval": settings_obj.require_manager_approval,
        "max_consecutive_leave_days": settings_obj.max_consecutive_leave_days,
        "carry_forward_enabled": settings_obj.carry_forward_enabled,
        "carry_forward_limit": settings_obj.carry_forward_limit,
        "leave_encashment_enabled": settings_obj.leave_encashment_enabled,
    }
    return _settings_response(data, "Leave settings updated successfully.")


@router.get(
    "/documents",
    status_code=status.HTTP_200_OK,
    summary="Retrieve document configuration",
)
async def get_document_settings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve organization-wide employee document configuration."""
    _require_role_in(claims, ALL_TENANT_READ_ROLES)
    cid = _get_valid_company_id(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.get_or_create_document_settings(cid)
    data = {
        "allowed_file_types": settings_obj.allowed_file_types or ["pdf", "jpg", "jpeg", "png"],
        "max_file_size_mb": settings_obj.max_file_size_mb,
        "require_document_verification": settings_obj.require_document_verification,
        "document_expiry_alert_days": settings_obj.document_expiry_alert_days,
        "employee_can_upload_documents": settings_obj.employee_can_upload_documents,
        "manager_can_view_documents": settings_obj.manager_can_view_documents,
    }
    return _settings_response(data, "Document settings retrieved successfully.")


@router.put(
    "/documents",
    status_code=status.HTTP_200_OK,
    summary="Update document configuration",
)
async def update_document_settings(
    payload: DocumentSettingsUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update organization-wide employee document configuration."""
    _require_role_in(
        claims,
        ALLOWED_DOCUMENT_SETTINGS_WRITE_ROLES,
        error_msg="Access denied: Only HR or authorized administrators can update document configuration.",
    )
    cid = _get_valid_company_id(claims)
    uid = _get_uid(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.update_document_settings(cid, payload, user_id=uid, claims=claims)
    data = {
        "allowed_file_types": settings_obj.allowed_file_types or ["pdf", "jpg", "jpeg", "png"],
        "max_file_size_mb": settings_obj.max_file_size_mb,
        "require_document_verification": settings_obj.require_document_verification,
        "document_expiry_alert_days": settings_obj.document_expiry_alert_days,
        "employee_can_upload_documents": settings_obj.employee_can_upload_documents,
        "manager_can_view_documents": settings_obj.manager_can_view_documents,
    }
    return _settings_response(data, "Document settings updated successfully.")


@router.get(
    "/assets",
    status_code=status.HTTP_200_OK,
    summary="Retrieve asset configuration",
)
async def get_asset_settings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve organization-wide asset management configuration."""
    _require_role_in(claims, ALL_TENANT_READ_ROLES)
    cid = _get_valid_company_id(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.get_or_create_asset_settings(cid)
    data = {
        "asset_id_prefix": settings_obj.asset_id_prefix,
        "require_assignment_approval": settings_obj.require_assignment_approval,
        "enable_asset_return_tracking": settings_obj.enable_asset_return_tracking,
        "enable_asset_condition_tracking": settings_obj.enable_asset_condition_tracking,
        "enable_warranty_reminders": settings_obj.enable_warranty_reminders,
        "warranty_reminder_days": settings_obj.warranty_reminder_days,
        "enable_asset_depreciation": settings_obj.enable_asset_depreciation,
    }
    return _settings_response(data, "Asset settings retrieved successfully.")


@router.put(
    "/assets",
    status_code=status.HTTP_200_OK,
    summary="Update asset configuration",
)
async def update_asset_settings(
    payload: AssetSettingsUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update organization-wide asset management configuration."""
    _require_role_in(
        claims,
        ALLOWED_ASSET_SETTINGS_WRITE_ROLES,
        error_msg="Access denied: Only IT or authorized administrators can update asset configuration.",
    )
    cid = _get_valid_company_id(claims)
    uid = _get_uid(claims)
    srv = SettingsManagementService(session)
    settings_obj = await srv.update_asset_settings(cid, payload, user_id=uid, claims=claims)
    data = {
        "asset_id_prefix": settings_obj.asset_id_prefix,
        "require_assignment_approval": settings_obj.require_assignment_approval,
        "enable_asset_return_tracking": settings_obj.enable_asset_return_tracking,
        "enable_asset_condition_tracking": settings_obj.enable_asset_condition_tracking,
        "enable_warranty_reminders": settings_obj.enable_warranty_reminders,
        "warranty_reminder_days": settings_obj.warranty_reminder_days,
        "enable_asset_depreciation": settings_obj.enable_asset_depreciation,
    }
    return _settings_response(data, "Asset settings updated successfully.")
