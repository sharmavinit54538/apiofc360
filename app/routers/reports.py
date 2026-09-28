"""Reports router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.misc import ReportExportRequest
from app.services.core_modules.misc_service import ReportsCoreService

router = APIRouter(prefix="/reports", tags=["Core - Reports"])


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
async def list_available_reports(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = ReportsCoreService(session)
    reports = await srv.list_reports(cid)
    return _ok(reports)


@router.get("/attendance")
async def get_attendance_report(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = ReportsCoreService(session)
    rep = await srv.get_attendance_report(cid, month=month, year=year)
    return _ok(rep)


@router.get("/export")
async def export_report_async(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    report_type: str = Query("attendance"),
    format: str = Query("csv"),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = ReportsCoreService(session)
    req = ReportExportRequest(report_type=report_type, format=format)
    res = await srv.export_report(cid, req)
    return _ok(res)
