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


def company_id(claims: dict) -> uuid.UUID:
    value = claims.get("company_id")
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required.")
    return uuid.UUID(str(value))


def user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(str(claims["sub"]))


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
