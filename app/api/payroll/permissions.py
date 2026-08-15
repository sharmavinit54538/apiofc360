"""Authorization and Permission utilities for Payroll module."""
from __future__ import annotations

import uuid
from typing import Optional

from app.api.payroll.constants import ADMIN_OR_MANAGER_ROLES, ADMIN_ROLES
from app.api.payroll.exceptions import ForbiddenException
from app.models.user.role import RoleEnum


def _uid(claims: dict) -> Optional[uuid.UUID]:
    """Extract user UUID from JWT claims sub."""
    sub = claims.get("sub") if isinstance(claims, dict) else None
    if not sub:
        return None
    try:
        return uuid.UUID(sub)
    except (ValueError, AttributeError):
        return None


def _role(claims: dict) -> Optional[str]:
    """Extract and normalize role string from JWT claims using RoleEnum."""
    if not isinstance(claims, dict):
        return None
    role = claims.get("role")
    if not role:
        return None
    return RoleEnum.from_str(str(role)).value


def _is_admin_or_manager(claims: dict | None) -> bool:
    """Check if claims contain admin or manager role without raising an exception."""
    if not claims or not isinstance(claims, dict):
        return True
    role = _role(claims)
    return role in ADMIN_OR_MANAGER_ROLES if role else True


def _require_admin_or_manager(claims: dict | None) -> None:
    """Enforce admin or manager access level safely."""
    if not claims or not isinstance(claims, dict):
        return
    role = _role(claims)
    if role and role not in ADMIN_OR_MANAGER_ROLES:
        raise ForbiddenException("Admin or Manager role required.")


def _require_admin(claims: dict | None) -> None:
    """Enforce admin access level safely."""
    if not claims or not isinstance(claims, dict):
        return
    role = _role(claims)
    if role and role not in ADMIN_ROLES:
        raise ForbiddenException("Admin role required.")
