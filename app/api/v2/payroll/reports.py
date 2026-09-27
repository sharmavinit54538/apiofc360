"""Reports router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.payroll_v2.reports import PayrollReportExportRequest
from app.services.payroll.report_service import PayrollReportService
from app.workers.payroll_tasks import dispatch_report_export

router = APIRouter(tags=["Payroll v2 - Reports"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# 1. GET /api/v2/payroll/reports/{reportKey}
@router.get("/reports/{reportKey}", summary="Fetch dynamic payroll report data")
async def get_payroll_report(
    reportKey: str,
    periodId: Optional[uuid.UUID] = Query(None),
    financialYear: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    employeeId: Optional[uuid.UUID] = Query(None),
    employeeStatus: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    designation: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    costCenter: Optional[str] = Query(None),
    employmentType: Optional[str] = Query(None),
    payrollStatus: Optional[str] = Query(None),
    paymentStatus: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    sortBy: Optional[str] = Query(None),
    sortDir: Optional[str] = Query("asc"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    filters = {
        "periodId": str(periodId) if periodId else None,
        "financialYear": financialYear,
        "month": month,
        "employeeId": str(employeeId) if employeeId else None,
        "employeeStatus": employeeStatus,
        "department": department,
        "designation": designation,
        "location": location,
        "costCenter": costCenter,
        "employmentType": employmentType,
        "payrollStatus": payrollStatus,
        "paymentStatus": paymentStatus,
    }
    # remove None filters
    clean_filters = {k: v for k, v in filters.items() if v is not None}

    data = await PayrollReportService.get_report_data(
        session=db,
        report_key=reportKey,
        filters=clean_filters,
        page=page,
        limit=limit,
        sort_by=sortBy,
        sort_dir=sortDir,
        company_id=c_uuid,
    )
    return _ok(data, f"Report '{reportKey}' generated successfully")


# 2. POST /api/v2/payroll/reports/{reportKey}/export
@router.post("/reports/{reportKey}/export", summary="Export payroll report asynchronously")
async def export_payroll_report(
    reportKey: str,
    payload: PayrollReportExportRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    export_id = uuid.uuid4()
    job_id = await dispatch_report_export(
        export_id=export_id,
        report_key=reportKey,
        file_format=payload.format,
        filters=payload.filters or {},
    )
    return _ok(
        {"exportId": str(export_id), "jobId": job_id, "status": "PENDING"},
        f"Export for report '{reportKey}' initiated",
    )


# 3. GET /api/v2/payroll/reports/exports/{exportId}/download
@router.get("/reports/exports/{exportId}/download", summary="Download completed report export file")
async def download_report_export(
    exportId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    content_bytes, filename = await PayrollReportService.get_export_download(db, export_id=exportId)
    return Response(
        content=content_bytes,
        media_type="text/csv" if filename.endswith(".csv") else "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
