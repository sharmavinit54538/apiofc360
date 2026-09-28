"""Recruiter router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.misc import JobPostingCreateRequest
from app.services.core_modules.misc_service import RecruiterCoreService

router = APIRouter(prefix="/recruiter", tags=["Core - Recruiter"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/jobs")
async def list_jobs(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = RecruiterCoreService(session)
    res = await srv.list_jobs(cid, status=status, page=page, limit=limit)
    return _ok(res)


@router.post("/jobs")
async def create_job(
    payload: JobPostingCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = RecruiterCoreService(session)
    job = await srv.create_job(cid, payload)
    return _ok({"id": str(job.id), "title": job.title, "status": job.status})


@router.get("/candidates")
async def list_candidates(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    talent_pool: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    _require_admin_or_manager(claims)
    srv = RecruiterCoreService(session)
    res = await srv.list_candidates(page=page, limit=limit, talent_pool=talent_pool)
    return _ok(res)
