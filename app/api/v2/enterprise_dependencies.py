"""Shared authenticated dependencies for Batch 6 enterprise APIs."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims

Claims = Annotated[dict, Depends(get_current_user_claims)]
Session = Annotated[AsyncSession, Depends(get_db_session)]
ADMIN_ROLES = {"admin", "hr_admin", "super_admin", "it_admin", "hr_manager"}
MANAGER_ROLES = ADMIN_ROLES | {"manager", "executive"}


async def get_autopilot_claims(claims: Claims) -> dict:
    """Autopilot controls company HR decisions; only HR and platform owners may use it."""
    from app.core.rbac import require_hr_admin
    require_hr_admin(claims)
    company_id(claims)
    user_id(claims)
    return claims


AutopilotClaims = Annotated[dict, Depends(get_autopilot_claims)]


def company_id(claims: dict) -> uuid.UUID:
    value = claims.get("company_id")
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required.")
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant claim.") from exc


def user_id(claims: dict) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims["sub"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Invalid actor claim.") from exc


def role(claims: dict) -> str:
    value = claims.get("role") or claims.get("user_role") or "employee"
    if isinstance(value, dict):
        value = value.get("name", "employee")
    return str(value).lower()


def require_admin(claims: dict) -> None:
    if role(claims) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="HR administrator access required.")


def require_manager(claims: dict) -> None:
    if role(claims) not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Manager or administrator access required.")


def ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message, "errors": None}


def translate(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc
