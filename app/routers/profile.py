"""Profile router for OFC360 / Aurix HRMS Core Modules (HR Employee Profile)."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.users_profile import ProfileUpdateRequest
from app.services.core_modules.users_profile_service import UsersProfileService

router = APIRouter(prefix="/profile", tags=["Core - Profile"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


@router.get("")
@router.get("/")
async def get_my_profile(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = UsersProfileService(session)
    emp = await srv.get_profile_by_user_id(uid)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    return _ok({
        "id": str(emp.id),
        "employee_id": emp.employee_id,
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "company_email": emp.company_email,
        "personal_email": emp.personal_email,
        "phone": emp.phone,
        "department": emp.department,
        "designation": emp.designation,
        "blood_group": emp.blood_group,
        "marital_status": emp.marital_status,
        "work_location": emp.work_location,
        "employment_type": emp.employment_type,
        "employment_status": emp.employment_status,
        "joining_date": emp.joining_date.isoformat() if emp.joining_date else None,
        "is_active": emp.is_active,
    })


@router.put("")
@router.put("/")
async def update_my_profile(
    payload: ProfileUpdateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = UsersProfileService(session)
    emp = await srv.update_profile(uid, payload)
    return _ok({
        "id": str(emp.id),
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "phone": emp.phone,
        "updated": True,
    })


@router.get("/documents")
async def get_profile_documents(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = UsersProfileService(session)
    emp = await srv.get_profile_by_user_id(uid)
    if not emp:
        return _ok([])
    docs = await srv.get_profile_documents(emp.id)
    return _ok(docs)


def _cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/assets")
async def get_profile_assets(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    cid = _cid(claims)
    srv = UsersProfileService(session)
    emp = await srv.get_profile_by_user_id(uid)
    if not emp:
        return _ok([])
    assets = await srv.get_profile_assets(emp.id, company_id=cid)
    return _ok(assets)


@router.get("/activity")
async def get_profile_activity(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    uid = _uid(claims)
    srv = UsersProfileService(session)
    activity = await srv.get_profile_activity(uid)
    return _ok(activity)
