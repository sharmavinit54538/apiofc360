"""Sidebar and Menu Permissions API router."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.schemas.auth import APIResponse
from app.middleware.auth import get_current_user_claims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sidebar", tags=["Sidebar Permissions"])

security = HTTPBearer(auto_error=False)


def _get_permissions_for_role(role: str) -> dict[str, Any]:
    role_lower = (role or "super_admin").lower()

    if role_lower in {"super_admin", "hr_admin", "executive", "it_admin"}:
        perms = [
            "all",
            "dashboard:read",
            "employees:read", "employees:write", "employees:create", "employees:delete",
            "departments:read", "departments:write", "departments:create", "departments:delete",
            "managers:read", "managers:write", "managers:create", "managers:delete",
            "attendance:read", "attendance:write",
            "leaves:read", "leaves:write", "leaves:approve",
            "payroll:read", "payroll:write",
            "recruitment:read", "recruitment:write",
            "documents:read", "documents:write",
            "settings:read", "settings:write",
            "reports:read", "exports:read"
        ]
        modules = {
            "dashboard": True, "employees": True, "departments": True,
            "managers": True, "recruitment": True, "attendance": True,
            "leaves": True, "payroll": True, "documents": True,
            "settings": True, "exports": True, "analytics": True
        }
    elif role_lower in {"hr_admin", "hr", "hr_manager", "hr_head"}:

        perms = [
            "dashboard:read",
            "employees:read", "employees:write", "employees:create",
            "departments:read", "departments:write",
            "managers:read",
            "attendance:read", "attendance:write",
            "leaves:read", "leaves:write", "leaves:approve",
            "payroll:read",
            "recruitment:read", "recruitment:write",
            "documents:read", "documents:write",
            "reports:read", "exports:read"
        ]
        modules = {
            "dashboard": True, "employees": True, "departments": True,
            "managers": True, "recruitment": True, "attendance": True,
            "leaves": True, "payroll": True, "documents": True,
            "settings": False, "exports": True, "analytics": True
        }
    elif role_lower in {"manager", "dept_manager", "team_lead"}:
        perms = [
            "dashboard:read",
            "employees:read",
            "departments:read",
            "attendance:read", "attendance:write",
            "leaves:read", "leaves:approve",
            "timesheets:read", "timesheets:approve",
            "documents:read",
            "reports:read"
        ]
        modules = {
            "dashboard": True, "employees": True, "departments": True,
            "managers": False, "recruitment": False, "attendance": True,
            "leaves": True, "payroll": False, "documents": True,
            "settings": False, "exports": False, "analytics": False
        }
    else:
        # Standard employee
        perms = [
            "dashboard:read",
            "portal:access",
            "checkin:create",
            "leaves:request",
            "attendance:read",
            "payslip:read"
        ]
        modules = {
            "dashboard": True, "employees": False, "departments": False,
            "managers": False, "recruitment": False, "attendance": True,
            "leaves": True, "payroll": True, "documents": True,
            "settings": False, "exports": False, "analytics": False
        }

    sidebar_items = [
        {"id": "dashboard", "title": "Dashboard", "path": "/dashboard", "icon": "layout-dashboard", "visible": modules.get("dashboard", True), "permissions": ["dashboard:read"]},
        {"id": "employees", "title": "Employees", "path": "/employees", "icon": "users", "visible": modules.get("employees", False), "permissions": ["employees:read"]},
        {"id": "departments", "title": "Departments", "path": "/departments", "icon": "building", "visible": modules.get("departments", False), "permissions": ["departments:read"]},
        {"id": "managers", "title": "Managers", "path": "/managers", "icon": "user-check", "visible": modules.get("managers", False), "permissions": ["managers:read"]},
        {"id": "recruitment", "title": "Recruitment & ATS", "path": "/recruitment", "icon": "briefcase", "visible": modules.get("recruitment", False), "permissions": ["recruitment:read"]},
        {"id": "attendance", "title": "Attendance", "path": "/attendance", "icon": "calendar-check", "visible": modules.get("attendance", False), "permissions": ["attendance:read"]},
        {"id": "leaves", "title": "Leave Management", "path": "/leaves", "icon": "plane-takeoff", "visible": modules.get("leaves", False), "permissions": ["leaves:read"]},
        {"id": "payroll", "title": "Payroll", "path": "/payroll", "icon": "banknote", "visible": modules.get("payroll", False), "permissions": ["payroll:read"]},
        {"id": "documents", "title": "Documents", "path": "/documents", "icon": "folder", "visible": modules.get("documents", False), "permissions": ["documents:read"]},
        {"id": "settings", "title": "Settings", "path": "/settings", "icon": "settings", "visible": modules.get("settings", False), "permissions": ["settings:write"]}
    ]

    return {
        "role": role_lower,
        "permissions": perms,
        "modules": modules,
        "sidebar": [item for item in sidebar_items if item["visible"]],
        "all_sidebar": sidebar_items,
    }


@router.get(
    "/permissions",
    status_code=status.HTTP_200_OK,
    summary="Get sidebar navigation permissions and menu structure",
)
@router.get(
    "/permissions/",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
@router.get(
    "",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def get_sidebar_permissions(
    request: Request,
    auth_credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
) -> APIResponse[dict]:
    """Return permissions, enabled modules, and sidebar navigation menu items for the current user."""
    from app.core.cache import cache_get, cache_set

    role = "employee"
    try:
        claims = await get_current_user_claims(request=request, credentials=auth_credentials)
        if claims and isinstance(claims, dict):
            raw_role = (claims.get("role") or "").lower().strip()
            raw_email = (claims.get("email") or "").lower().strip()
            if raw_role == "super_admin":
                if raw_email == "superadmin@ofc360.com":
                    role = "super_admin"
                else:
                    role = "employee"
            else:
                role = raw_role or "employee"
    except Exception as exc:
        logger.debug("Unauthenticated sidebar permissions call, returning default employee permissions: %s", exc)
        role = "employee"

    cache_key = f"sidebar_perms:{role}"
    cached_data = cache_get(cache_key)
    if cached_data is None:
        cached_data = _get_permissions_for_role(role)
        cache_set(cache_key, cached_data, ttl_seconds=300.0)

    return APIResponse[dict](
        success=True,
        message="Sidebar permissions retrieved successfully.",
        data=cached_data,
        errors=None,
    )
