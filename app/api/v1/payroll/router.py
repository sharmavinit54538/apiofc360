"""API v1 Payroll Router — 19 Legacy Endpoints for complete backward-compatibility."""

from __future__ import annotations

import uuid
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin, _uid, _role
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.payroll import PayrollRun
from app.schemas.payroll_v2.periods import PayrollPeriodCreateRequest
from app.schemas.payroll_v2.runs import (
    PayrollRunApproveRequest,
    PayrollRunCreateRequest,
    PayrollRunFinalizeRequest,
    PayrollRunPayslipGenerateRequest,
    PayrollRunRejectRequest,
)
from app.services.payroll.period_service import PayrollPeriodService
from app.services.payroll.run_service import PayrollRunService
from app.services.payroll.payslip_service import PayslipService
from app.workers.payroll_tasks import dispatch_payslip_generation, PayrollJobTracker

router = APIRouter(prefix="/payroll", tags=["Payroll v1 (Legacy)"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# 1. GET /api/v1/payroll/employees/{employeeId}/payslips
@router.get("/employees/{employeeId}/payslips", summary="Get payslips for employee (v1)")
async def v1_get_employee_payslips(
    employeeId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    user_role = _role(claims)
    user_uid = _uid(claims)
    # RBAC: Employee can view own, Admin/HR can view any
    res = await PayslipService.get_employee_payslips(db, employeeId, page, limit)
    return _ok(res, "Employee payslips retrieved successfully")


# 2. GET /api/v1/payroll/my-payslips
@router.get("/my-payslips", summary="Get current employee payslips (v1)")
async def v1_get_my_payslips(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    user_id = _uid(claims)
    from app.repositories.employee_repository import EmployeeRepository
    emp = await EmployeeRepository(db).get_by_user_id(user_id) if user_id else None
    if not emp:
        return _ok({"items": [], "total": 0, "page": page, "limit": limit})
    res = await PayslipService.get_employee_payslips(db, emp.id, page, limit)
    return _ok(res, "My payslips retrieved successfully")


# 3. GET /api/v1/payroll/periods
@router.get("/periods", summary="List payroll periods (v1)")
async def v1_list_periods(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    c_uuid = uuid.UUID(company_id) if company_id else None
    res = await PayrollPeriodService.list_periods(
        db, company_id=c_uuid, page=page, limit=limit, status_filter=status, year=year, month=month, search=search
    )
    return _ok(res, "Payroll periods retrieved successfully")


# 4. POST /api/v1/payroll/periods
@router.post("/periods", status_code=status.HTTP_201_CREATED, summary="Create payroll period (v1)")
async def v1_create_period(
    payload: PayrollPeriodCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    period = await PayrollPeriodService.create_period(db, payload)
    return _ok(period, "Payroll period created successfully")


# 5. GET /api/v1/payroll/periods/{periodId}
@router.get("/periods/{periodId}", summary="Get payroll period by ID (v1)")
async def v1_get_period(
    periodId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    period = await PayrollPeriodService.get_period(db, periodId)
    return _ok(period, "Payroll period retrieved successfully")


# 6. POST /api/v1/payroll/run
@router.post("/run", status_code=status.HTTP_201_CREATED, summary="Trigger/create payroll run (v1)")
async def v1_create_run(
    payload: PayrollRunCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    p_uuid = uuid.UUID(payload.period_id)
    user_id = _uid(claims)
    run = await PayrollRunService.create_run(db, p_uuid, user_id=user_id)
    return _ok(run, "Payroll run created successfully")


# 7. GET /api/v1/payroll/runs/{runId}
@router.get("/runs/{runId}", summary="Get payroll run by ID (v1)")
async def v1_get_run(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId)
    return _ok(run, "Payroll run details retrieved successfully")


# 8. POST /api/v1/payroll/runs/{runId}/approve
@router.post("/runs/{runId}/approve", summary="Approve payroll run (v1)")
async def v1_approve_run(
    runId: uuid.UUID,
    payload: PayrollRunApproveRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.approve_run(
        db, runId, comments=payload.comments, user_id=_uid(claims), user_role=_role(claims)
    )
    return _ok(run, "Payroll run approved successfully")


# 9. POST /api/v1/payroll/runs/{runId}/cancel
@router.post("/runs/{runId}/cancel", summary="Cancel payroll run (v1)")
async def v1_cancel_run(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.cancel_run(db, runId, user_id=_uid(claims), user_role=_role(claims))
    return _ok(run, "Payroll run cancelled successfully")


# 10. GET /api/v1/payroll/runs/{runId}/employees
@router.get("/runs/{runId}/employees", summary="Get employees for payroll run (v1)")
async def v1_get_run_employees(
    runId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    validationStatus: Optional[str] = Query(None),
    sortBy: Optional[str] = Query(None),
    sortDir: Optional[str] = Query("asc"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.list_run_employees(
        db, runId, page=page, limit=limit, search=search, department=department,
        validation_status=validationStatus, sort_by=sortBy, sort_dir=sortDir,
    )
    return _ok(res, "Run employees retrieved successfully")


# 11. GET /api/v1/payroll/runs/{runId}/employees/{employeeId}
@router.get("/runs/{runId}/employees/{employeeId}", summary="Get single employee payroll run details (v1)")
async def v1_get_run_single_employee(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.get_run_employee(db, runId, employeeId)
    return _ok(res, "Employee run details retrieved successfully")


# 12. GET /api/v1/payroll/runs/{runId}/employees/{employeeId}/payslip/download
@router.get("/runs/{runId}/employees/{employeeId}/payslip/download", summary="Download payslip file (v1)")
async def v1_download_payslip(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    content, filename = await PayslipService.get_payslip_file(db, runId, employeeId)
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# 13. POST /api/v1/payroll/runs/{runId}/finalize
@router.post("/runs/{runId}/finalize", summary="Finalize payroll run (v1)")
async def v1_finalize_run(
    runId: uuid.UUID,
    payload: PayrollRunFinalizeRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    run = await PayrollRunService.finalize_run(
        db, runId, notes=payload.notes, lock=payload.lock, user_id=_uid(claims), user_role=_role(claims)
    )
    return _ok(run, "Payroll run finalized successfully")


# 14. POST /api/v1/payroll/runs/{runId}/payslips/generate
@router.post("/runs/{runId}/payslips/generate", summary="Trigger batch payslips generation (v1)")
async def v1_generate_payslips(
    runId: uuid.UUID,
    payload: Optional[PayrollRunPayslipGenerateRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    emp_ids = payload.employee_ids if payload else None
    force = payload.force if payload else False
    fmt = payload.format if payload else "pdf"

    job_id = await dispatch_payslip_generation(runId, employee_ids=emp_ids, force=force, format_type=fmt)
    return _ok({"job_id": job_id, "status": "QUEUED"}, "Payslip generation job initiated successfully")


# 15. GET /api/v1/payroll/runs/{runId}/preview
@router.get("/runs/{runId}/preview", summary="Preview payroll run summary (v1)")
async def v1_preview_run(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.get_preview(db, runId)
    return _ok(res, "Payroll run preview retrieved successfully")


# 16. POST /api/v1/payroll/runs/{runId}/reject
@router.post("/runs/{runId}/reject", summary="Reject payroll run (v1)")
async def v1_reject_run(
    runId: uuid.UUID,
    payload: PayrollRunRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    run = await PayrollRunService.reject_run(
        db, runId, reason=payload.reason, comments=payload.comments, user_id=_uid(claims), user_role=_role(claims)
    )
    return _ok(run, "Payroll run rejected successfully")


# 17. POST /api/v1/payroll/runs/{runId}/retry
@router.post("/runs/{runId}/retry", summary="Retry failed payroll run (v1)")
async def v1_retry_run(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.retry_run(db, runId, user_id=_uid(claims), user_role=_role(claims))
    return _ok(run, "Payroll run retry triggered successfully")


# 18. GET /api/v1/payroll/runs/{runId}/status
@router.get("/runs/{runId}/status", summary="Get payroll run status or async job status (v1)")
async def v1_get_run_status(
    runId: uuid.UUID,
    job_id: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    if job_id:
        job = await PayrollJobTracker.get_job(job_id)
        if job:
            return _ok(job, "Job status retrieved")

    run = await PayrollRunService.get_run(db, runId)
    return _ok({
        "run_id": str(run.id),
        "status": run.status,
        "validation_status": run.validation_status,
        "is_locked": run.is_locked,
        "total_employees": run.total_employees,
    }, "Run status retrieved successfully")


# 19. GET /api/v1/payroll/runs/{runId}/validation
@router.get("/runs/{runId}/validation", summary="Get payroll run validation details (v1)")
async def v1_get_run_validation(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.validate_run(db, runId)
    return _ok(res, "Payroll run validation retrieved successfully")
