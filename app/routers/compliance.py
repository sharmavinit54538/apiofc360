"""Compliance router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.core_modules.compliance_health_service import ComplianceService

router = APIRouter(prefix="/compliance", tags=["Core - Compliance"])


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
async def list_compliance(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = ComplianceService(session)
    res = await srv.list_records(company_id=cid, page=page, limit=limit)
    return _ok(res)


@router.get("/dashboard")
async def get_compliance_dashboard(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = ComplianceService(session)
    res = await srv.get_dashboard_status(cid)
    return _ok(res)


@router.get("/status")
async def get_compliance_status(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = ComplianceService(session)
    res = await srv.get_dashboard_status(cid)
    return _ok(res)


@router.get("/documents")
async def list_compliance_documents(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = ComplianceService(session)
    res = await srv.list_records(company_id=cid, page=page, limit=limit)
    return _ok(res)
