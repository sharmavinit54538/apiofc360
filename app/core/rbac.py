"""Role-based access control (RBAC) FastAPI dependencies."""

from __future__ import annotations

import logging
from typing import Annotated, Callable, Sequence
import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.user.role import OFFICIAL_SUPER_ADMIN_EMAIL, RoleEnum, UserRole

logger = logging.getLogger(__name__)

# Re-export canonical RoleEnum and UserRole
__all__ = [
    "RoleEnum",
    "UserRole",
    "OFFICIAL_SUPER_ADMIN_EMAIL",
    "ROLE_SUPER_ADMIN",
    "ROLE_HR_ADMIN",
    "ROLE_IT_ADMIN",
    "ROLE_EXECUTIVE",
    "ROLE_MANAGER",
    "ROLE_EMPLOYEE",
    "ROLE_INTERN",
    "ADMIN_ROLES",
    "ADMIN_MANAGER_ROLES",
    "EXECUTIVE_ROLES",
    "require_super_admin",
    "require_admin",
    "require_hr_admin",
    "require_it_admin",
    "require_admin_or_manager",
    "require_executive",
    "require_employee_or_above",
    "require_roles",
]

ROLE_SUPER_ADMIN = RoleEnum.SUPER_ADMIN.value
ROLE_HR_ADMIN = RoleEnum.HR_ADMIN.value
ROLE_IT_ADMIN = RoleEnum.IT_ADMIN.value
ROLE_EXECUTIVE = RoleEnum.EXECUTIVE.value
ROLE_MANAGER = RoleEnum.MANAGER.value
ROLE_EMPLOYEE = RoleEnum.EMPLOYEE.value
ROLE_INTERN = RoleEnum.INTERN.value

ADMIN_ROLES = {ROLE_HR_ADMIN, ROLE_IT_ADMIN}
ADMIN_MANAGER_ROLES = {ROLE_HR_ADMIN, ROLE_IT_ADMIN, ROLE_MANAGER, ROLE_EXECUTIVE}
EXECUTIVE_ROLES = {ROLE_SUPER_ADMIN, ROLE_HR_ADMIN, ROLE_EXECUTIVE}


def _is_valid_super_admin_claims(claims: dict) -> bool:
    """Validate that claims represent the official, authorized Super Admin."""
    role = (claims.get("role") or "").lower().strip()
    email = (claims.get("email") or "").lower().strip()
    if role != ROLE_SUPER_ADMIN:
        return False
    # If email is in claims, it must match the single authorized Super Admin email
    if email and email != OFFICIAL_SUPER_ADMIN_EMAIL:
        return False
    return True


def require_hr_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with hr_admin or official super_admin roles."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role == ROLE_HR_ADMIN:
        return claims
    if user_role == ROLE_SUPER_ADMIN and _is_valid_super_admin_claims(claims):
        return claims

    logger.warning(
        "RBAC: HR Admin access required | user_role=%s | user_id=%s",
        claims.get("role"),
        claims.get("sub"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="HR Admin access required.",
    )


def require_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with administrative rights (official super_admin, hr_admin, it_admin)."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role in ADMIN_ROLES:
        return claims
    if user_role == ROLE_SUPER_ADMIN and _is_valid_super_admin_claims(claims):
        return claims

    logger.warning(
        "RBAC: Admin/HR access required | user_role=%s | user_id=%s",
        claims.get("role"),
        claims.get("sub"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin or HR access required.",
    )


def require_admin_or_manager(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with official super_admin, hr_admin, it_admin, manager, or executive roles."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role in ADMIN_MANAGER_ROLES:
        return claims
    if user_role == ROLE_SUPER_ADMIN and _is_valid_super_admin_claims(claims):
        return claims

    logger.warning(
        "RBAC: Admin/HR/Manager access required | user_role=%s | user_id=%s",
        claims.get("role"),
        claims.get("sub"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin, HR, or Manager access required.",
    )


def require_executive(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow users with executive, hr_admin, or official super_admin roles."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role in EXECUTIVE_ROLES:
        if user_role == ROLE_SUPER_ADMIN and not _is_valid_super_admin_claims(claims):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Super Admin access required.",
            )
        return claims

    logger.warning(
        "RBAC: Executive access required | user_role=%s | user_id=%s",
        claims.get("role"),
        claims.get("sub"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Executive access required.",
    )


def require_it_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Allow IT admin or official super_admin users."""
    user_role = (claims.get("role") or "").lower().strip()
    if user_role == ROLE_IT_ADMIN:
        return claims
    if user_role == ROLE_SUPER_ADMIN and _is_valid_super_admin_claims(claims):
        return claims

    logger.warning(
        "RBAC: IT Admin access required | user_role=%s | user_id=%s",
        claims.get("role"),
        claims.get("sub"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="IT Admin access required.",
    )


def require_employee_or_above(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> dict:
    """Ensure request is from an authenticated user with a recognized platform role."""
    user_role = (claims.get("role") or "").lower().strip()
    all_valid_roles = {r.value for r in RoleEnum}
    if user_role in all_valid_roles:
        if user_role == ROLE_SUPER_ADMIN and not _is_valid_super_admin_claims(claims):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Super Admin access required.",
            )
        return claims

    logger.warning(
        "RBAC: Valid role required | user_role=%s | user_id=%s",
        claims.get("role"),
        claims.get("sub"),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied.",
    )


def require_roles(*allowed_roles: RoleEnum | str) -> Callable[[dict], dict]:
    """Dependency factory that restricts route access to specified roles."""
    normalized_allowed: set[str] = set()
    for r in allowed_roles:
        if isinstance(r, RoleEnum):
            normalized_allowed.add(r.value)
        elif isinstance(r, str):
            normalized_allowed.add(RoleEnum.from_str(r).value)

    def _role_checker(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
        user_role = (claims.get("role") or "").lower().strip()
        if user_role in normalized_allowed:
            if user_role == ROLE_SUPER_ADMIN and not _is_valid_super_admin_claims(claims):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Super Admin access required.",
                )
            return claims

        # Super admin always allowed unless specifically disallowed
        if user_role == ROLE_SUPER_ADMIN and _is_valid_super_admin_claims(claims):
            return claims

        logger.warning(
            "RBAC: Insufficient role permissions | required=%s | user_role=%s | user_id=%s",
            normalized_allowed,
            user_role,
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to access this resource.",
        )

    return _role_checker


async def require_super_admin(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession | None, Depends(get_db_session)] = None,
) -> dict:
    """Allow only the official, active Super Admin identity (superadmin@ofc360.com)."""
    user_role = (claims.get("role") or "").lower().strip()
    claim_email = (claims.get("email") or "").lower().strip()

    # 1. Strict role claim check
    if user_role != ROLE_SUPER_ADMIN:
        logger.warning(
            "RBAC: Super admin role required | user_role=%s | user_id=%s",
            claims.get("role"),
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin access required.",
        )

    # 2. Strict email claim check if claim email is present
    if claim_email and claim_email != OFFICIAL_SUPER_ADMIN_EMAIL:
        logger.warning(
            "RBAC: Non-authorized email attempted Super Admin access | email=%s | user_id=%s",
            claim_email,
            claims.get("sub"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin access required.",
        )

    # 3. Database-level immutable identity and active status verification
    if session is not None:
        user_id_raw = claims.get("sub")
        if not user_id_raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload.",
            )
        try:
            user_id = uuid.UUID(str(user_id_raw))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user ID in token.",
            )

        from app.repositories.auth_repository import AuthRepository
        repo = AuthRepository(session)
        user = await repo.get_user_by_id(user_id)
        if not user or user.is_deleted:
            logger.warning("RBAC: Super Admin resolution failed: User %s not found in DB or is deleted.", user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account no longer exists.",
            )
        if not user.is_active:
            logger.warning("RBAC: Super Admin resolution rejected: User %s is inactive.", user_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive or disabled.",
            )

        db_role = user.role.value if hasattr(user.role, "value") else str(user.role).lower()
        db_email = (user.email or "").strip().lower()

        if db_email != OFFICIAL_SUPER_ADMIN_EMAIL or db_role != ROLE_SUPER_ADMIN:
            logger.warning(
                "RBAC: Super Admin identity check failed: DB user (email=%s, role=%s) does not match required superadmin.",
                db_email,
                db_role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Super Admin access required.",
            )

    return claims
