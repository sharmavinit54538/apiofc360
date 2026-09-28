"""Statutory Compliance router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.payroll_v2.statutory import StatutoryReportRequest
from app.services.payroll.statutory_service import StatutoryService
from app.workers.payroll_tasks import dispatch_statutory_report

router = APIRouter(tags=["Payroll v2 - Statutory"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# 1. GET /api/v2/payroll/statutory/config
@router.get("/statutory/config", summary="Get statutory compliance configuration (PF, ESI, PT, TDS)")
async def get_statutory_config(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    config = await StatutoryService.get_config(db, company_id=c_uuid)
    return _ok(config, "Statutory configuration retrieved successfully")


# 2. POST /api/v2/payroll/statutory/reports/{component}
@router.post("/statutory/reports/{component}", summary="Generate statutory authority returns (e.g. PF ECR)")
async def generate_statutory_report(
    component: str,
    payload: StatutoryReportRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    comp_upper = component.upper().strip()
    if comp_upper not in ("PF", "ESI", "PT", "TDS"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="component must be one of: PF, ESI, PT, TDS",
        )
    p_uuid = uuid.UUID(payload.period_id)
    job_id = await dispatch_statutory_report(
        component=comp_upper, period_id=p_uuid, file_format=payload.format
    )
    return _ok(
        {"jobId": job_id, "component": comp_upper, "periodId": str(p_uuid), "status": "QUEUED"},
        f"Statutory {comp_upper} report generation dispatched",
    )


# 3. GET /api/v2/payroll/statutory/summary
@router.get("/statutory/summary", summary="Get statutory liability summary for a period")
async def get_statutory_summary(
    periodId: uuid.UUID = Query(..., description="Payroll period UUID"),
    component: Optional[str] = Query(None, description="PF, ESI, PT, TDS or ALL"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    summary = await StatutoryService.get_summary(
        session=db, period_id=periodId, component=component, company_id=c_uuid
    )
    return _ok(summary, "Statutory summary retrieved successfully")
