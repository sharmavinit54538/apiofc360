"""Users router for OFC360 / Aurix HRMS Core Modules (Auth/Account Identity level)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin, _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.users_profile import UserUpdateRequest
from app.services.core_modules.users_profile_service import UsersProfileService

router = APIRouter(prefix="/users", tags=["Core - Users"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("")
@router.get("/")
async def list_users(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    role: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = UsersProfileService(session)
    res = await srv.list_users(company_id=cid, role=role, page=page, limit=limit)
    return _ok(res)


@router.get("/me")
async def get_current_user_details(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = UsersProfileService(session)
    user = await srv.get_user_by_id(uid)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found")
    return _ok({
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "account_status": getattr(user, "account_status", "ACTIVE"),
        "company_id": str(user.company_id) if user.company_id else None,
    })


@router.get("/{id}")
async def get_user_by_id(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    srv = UsersProfileService(session)
    user = await srv.get_user_by_id(id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _ok({
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "role": user.role,
        "is_active": user.is_active,
    })


@router.put("/{id}")
async def update_user(
    id: uuid.UUID,
    payload: UserUpdateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    srv = UsersProfileService(session)
    user = await srv.update_user(id, payload)
    return _ok({"id": str(user.id), "email": user.email, "role": user.role, "updated": True})
