"""Reports router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.payroll_v2.reports import PayrollReportExportRequest
from app.services.payroll.report_service import PayrollReportService
from app.services.payroll.parallel_comparison_service import ParallelPayrollComparisonService
from app.models.payroll_models import ParallelPayrollComparisonReport
from app.workers.payroll_tasks import dispatch_report_export

router = APIRouter(tags=["Payroll v2 - Reports"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}




def _comparison_dict(report: ParallelPayrollComparisonReport) -> dict[str, Any]:
    return {
        "id": str(report.id), "report_id": str(report.id), "run_id": str(report.run_id),
        "company_id": str(report.company_id) if report.company_id else None,
        "legacy_file_name": report.legacy_file_name,
        "legacy_file_sha256": report.legacy_file_sha256,
        "status": report.status, "summary": report.summary or {},
        "employee_variances": report.employee_variances or [],
        "employees": report.employee_variances or [],
        "head_variances": report.head_variances or {},
        "heads": report.head_variances or {},
        "diagnoses": report.diagnoses or [],
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/reports/comparison", summary="Fetch a persisted parallel payroll comparison")
async def get_parallel_payroll_comparison(
    runId: Optional[uuid.UUID] = Query(None),
    reportId: Optional[uuid.UUID] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id = uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None
    if reportId:
        report = await ParallelPayrollComparisonService.get_report(db, reportId, company_id)
        return _ok(_comparison_dict(report), "Parallel payroll comparison retrieved successfully")
    stmt = select(ParallelPayrollComparisonReport).order_by(desc(ParallelPayrollComparisonReport.created_at))
    if company_id:
        stmt = stmt.where(ParallelPayrollComparisonReport.company_id == company_id)
    if runId:
        stmt = stmt.where(ParallelPayrollComparisonReport.run_id == runId)
        report = (await db.execute(stmt.limit(1))).scalars().first()
        if report is None:
            return _ok({"run_id": str(runId), "status": "NOT_GENERATED", "employee_variances": [], "head_variances": {}, "diagnoses": []}, "No parallel comparison has been generated for this run")
        return _ok(_comparison_dict(report), "Parallel payroll comparison retrieved successfully")
    reports = list((await db.execute(stmt.limit(100))).scalars().all())
    return _ok({"items": [_comparison_dict(r) for r in reports], "total": len(reports)}, "Parallel payroll comparisons retrieved successfully")


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
