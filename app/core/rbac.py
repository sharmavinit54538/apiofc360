"""Role-based access control (RBAC) FastAPI dependencies."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.middleware.auth import get_current_user_claims

logger = logging.getLogger(__name__)

ROLE_SUPER_ADMIN = "super_admin"
ROLE_HR_ADMIN = "hr_admin"
ROLE_IT_ADMIN = "it_admin"
ROLE_EXECUTIVE = "executive"
ROLE_MANAGER = "manager"
ROLE_EMPLOYEE = "employee"

ADMIN_ROLES = {ROLE_SUPER_ADMIN, ROLE_HR_ADMIN, ROLE_IT_ADMIN}
ADMIN_MANAGER_ROLES = {ROLE_SUPER_ADMIN, ROLE_HR_ADMIN, ROLE_IT_ADMIN, ROLE_MANAGER}


def require_hr_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with hr_admin or super_admin roles."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role not in {ROLE_HR_ADMIN, ROLE_SUPER_ADMIN}:
        logger.warning(
            "RBAC: HR Admin access required | user_role=%s | user_id=%s",
            claims.get("role"),
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="HR Admin access required.",
        )
    return claims


def require_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with administrative rights (super_admin, hr_admin, it_admin)."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role not in ADMIN_ROLES:
        logger.warning(
            "RBAC: Admin/HR access required | user_role=%s | user_id=%s",
            claims.get("role"),
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or HR access required.",
        )
    return claims


def require_admin_or_manager(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with super_admin, hr_admin, or manager roles."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role not in ADMIN_MANAGER_ROLES:
        logger.warning(
            "RBAC: Admin/HR/Manager access required | user_role=%s | user_id=%s",
            claims.get("role"),
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin, HR, or Manager access required.",
        )
    return claims


def require_super_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow only super_admin users."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role != ROLE_SUPER_ADMIN:
        logger.warning(
            "RBAC: Super admin access required | user_role=%s | user_id=%s",
            claims.get("role"),
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin access required.",
        )
    return claims


def require_it_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow IT admin or super_admin users."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role not in {ROLE_IT_ADMIN, ROLE_SUPER_ADMIN}:
        logger.warning(
            "RBAC: IT Admin access required | user_role=%s | user_id=%s",
            claims.get("role"),
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IT Admin access required.",
        )
    return claims

