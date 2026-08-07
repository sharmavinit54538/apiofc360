"""Role-based access control (RBAC) FastAPI dependencies."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.middleware.auth import get_current_user_claims

logger = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_HR = "hr"
ROLE_MANAGER = "manager"
ROLE_EMPLOYEE = "employee"

ADMIN_ROLES = {ROLE_ADMIN, ROLE_HR, "ceo", "cfo", "cto", "coo", "cmo", "clo", "ciso", "cio"}
ADMIN_MANAGER_ROLES = {ROLE_ADMIN, ROLE_HR, ROLE_MANAGER, "ceo", "cfo", "cto", "coo", "cmo", "clo", "ciso", "cio"}


def require_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with administrative rights (admin, hr, ceo, csuite)."""
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
    """Allow users with admin, hr, manager, or C-suite executive roles."""
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
