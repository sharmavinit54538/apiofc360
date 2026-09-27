"""Payroll Runs router for Payroll v2 (All 22+ Lifecycle Endpoints)."""

from __future__ import annotations

import uuid
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.models.payroll import PayrollRun
from app.schemas.payroll_v2.runs import (
    PayrollRunApproveRequest,
    PayrollRunCreateRequest,
    PayrollRunFinalizeRequest,
    PayrollRunPaymentBatchCreateRequest,
    PayrollRunPayslipGenerateRequest,
    PayrollRunRejectRequest,
    PayrollRunSendBackRequest,
)
from app.services.payroll.payment_batch_service import PaymentBatchService
from app.services.payroll.payslip_service import PayslipService
from app.services.payroll.run_service import PayrollRunService
from app.workers.payroll_tasks import (
    PayrollJobTracker,
    dispatch_payroll_processing,
    dispatch_payslip_generation,
)

router = APIRouter(tags=["Payroll v2 - Runs"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _run_dict(r: PayrollRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "company_id": str(r.company_id) if r.company_id else None,
        "period_id": str(r.period_id) if r.period_id else None,
        "run_number": r.run_number,
        "period_month": r.period_month,
        "period_year": r.period_year,
        "status": r.status,
        "total_employees": r.total_employees,
        "total_gross": float(r.total_gross or 0),
        "total_deductions": float(r.total_deductions or 0),
        "total_net": float(r.total_net or 0),
        "total_gross_paise": r.total_gross_paise,
        "total_deductions_paise": r.total_deductions_paise,
        "total_net_paise": r.total_net_paise,
        "validation_status": r.validation_status,
        "validation_errors": r.validation_errors,
        "is_locked": r.is_locked,
        "notes": r.notes,
        "comments": r.comments,
        "approved_by": str(r.approved_by) if r.approved_by else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
        "finalized_by": str(r.finalized_by) if r.finalized_by else None,
        "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
        "rejected_by": str(r.rejected_by) if r.rejected_by else None,
        "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
        "rejection_reason": r.rejection_reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# Optional helper endpoints for comprehensive API completeness
@router.get("/runs", summary="List payroll runs")
async def list_runs_v2(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    stmt = select(PayrollRun)
    if company_id_str:
        stmt = stmt.where(PayrollRun.company_id == uuid.UUID(company_id_str))
    runs = (await db.execute(stmt)).scalars().all()
    return _ok([_run_dict(r) for r in runs], "Payroll runs retrieved successfully")


@router.post("/runs", status_code=status.HTTP_201_CREATED, summary="Create a new payroll run")
async def create_run_v2(
    payload: PayrollRunCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    p_uuid = uuid.UUID(payload.period_id)
    run = await PayrollRunService.create_run(
        session=db,
        period_id=p_uuid,
        company_id=c_uuid,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_run_dict(run), f"Payroll run created for period {p_uuid}")


@router.get("/runs/{runId}", summary="Get payroll run details")
async def get_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId)
    return _ok(_run_dict(run), "Payroll run details retrieved successfully")


# 1. DELETE /api/v2/payroll/runs/{runId}
@router.delete("/runs/{runId}", summary="Delete draft payroll run")
async def delete_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.delete_run(db, run_id=runId)
    return _ok(res, "Payroll run deleted successfully")


# 2. GET /api/v2/payroll/runs/{runId}/approval
@router.get("/runs/{runId}/approval", summary="Get approval status and details for payroll run")
async def get_run_approval_details(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId)
    return _ok({
        "run_id": str(run.id),
        "status": run.status,
        "is_approved": run.status in ("APPROVED", "FINALIZED"),
        "approved_by": str(run.approved_by) if run.approved_by else None,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "comments": run.comments,
        "rejection_reason": run.rejection_reason,
    }, "Approval status retrieved successfully")


# 3. POST /api/v2/payroll/runs/{runId}/approve
@router.post("/runs/{runId}/approve", summary="Approve payroll run")
async def approve_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunApproveRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    comments = payload.comments if payload else None
    run = await PayrollRunService.approve_run(
        session=db,
        run_id=runId,
        comments=comments,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_run_dict(run), "Payroll run approved successfully")


# 4. GET /api/v2/payroll/runs/{runId}/employees
@router.get("/runs/{runId}/employees", summary="List employee calculation items in payroll run")
async def list_run_employees_v2(
    runId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
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
        session=db,
        run_id=runId,
        page=page,
        limit=limit,
        search=search,
        department=department,
        validation_status=validationStatus,
        sort_by=sortBy,
        sort_dir=sortDir,
    )
    return _ok(res, "Run employees retrieved successfully")


# 5. GET /api/v2/payroll/runs/{runId}/employees/{employeeId}
@router.get("/runs/{runId}/employees/{employeeId}", summary="Get calculation breakdown for employee in run")
async def get_run_employee_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.get_run_employee(db, run_id=runId, employee_id=employeeId)
    return _ok(res, "Employee run breakdown retrieved successfully")


# 6. GET /api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip
@router.get("/runs/{runId}/employees/{employeeId}/payslip", summary="Get payslip JSON breakdown for employee in run")
async def get_run_employee_payslip_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayslipService.get_payslip_detail(db, run_id=runId, employee_id=employeeId)
    return _ok(res, "Employee payslip retrieved successfully")


# 7. GET /api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip/download
@router.get("/runs/{runId}/employees/{employeeId}/payslip/download", summary="Download payslip document for employee in run")
async def download_run_employee_payslip_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    content_bytes, filename = await PayslipService.get_payslip_file(db, run_id=runId, employee_id=employeeId)
    return Response(
        content=content_bytes,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# 8. GET /api/v2/payroll/runs/{runId}/finalization
@router.get("/runs/{runId}/finalization", summary="Get finalization summary and lock status for run")
async def get_run_finalization_summary(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId)
    return _ok({
        "run_id": str(run.id),
        "is_finalized": run.status == "FINALIZED",
        "is_locked": run.is_locked,
        "finalized_by": str(run.finalized_by) if run.finalized_by else None,
        "finalized_at": run.finalized_at.isoformat() if run.finalized_at else None,
        "total_employees": run.total_employees,
        "total_net_paise": run.total_net_paise,
        "notes": run.notes,
    }, "Finalization summary retrieved successfully")


# 9. POST /api/v2/payroll/runs/{runId}/finalize
@router.post("/runs/{runId}/finalize", summary="Finalize payroll run")
async def finalize_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunFinalizeRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    notes = payload.notes if payload else None
    lock = payload.lock if payload else True
    run = await PayrollRunService.finalize_run(
        session=db,
        run_id=runId,
        notes=notes,
        lock=lock,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_run_dict(run), "Payroll run finalized successfully")


# 10. GET /api/v2/payroll/runs/{runId}/generation-status
@router.get("/runs/{runId}/generation-status", summary="Poll async generation/calculation status")
async def get_run_generation_status(
    runId: uuid.UUID,
    job_id: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId)
    target_job = job_id or run.job_id
    job_data = await PayrollJobTracker.get_job(target_job) if target_job else None
    return _ok({
        "run_id": str(run.id),
        "run_status": run.status,
        "job_id": target_job,
        "job": job_data or {
            "status": "COMPLETED" if run.status in ("CALCULATED", "APPROVED", "FINALIZED") else "UNKNOWN",
            "progress": 100 if run.status in ("CALCULATED", "APPROVED", "FINALIZED") else 0,
        },
    }, "Generation status retrieved successfully")


# 11. POST /api/v2/payroll/runs/{runId}/payment-batches
@router.post("/runs/{runId}/payment-batches", status_code=status.HTTP_201_CREATED, summary="Create payment batch from run")
async def create_payment_batch_from_run(
    runId: uuid.UUID,
    payload: PayrollRunPaymentBatchCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    src_uuid = uuid.UUID(payload.source_account_id)
    batch = await PaymentBatchService.create_batch_from_run(
        session=db,
        run_id=runId,
        source_account_id=src_uuid,
        payment_mode=payload.payment_mode,
        held_employee_ids=payload.held_employee_ids,
        notes=payload.notes,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok({
        "id": str(batch.id),
        "run_id": str(batch.payroll_run_id),
        "batch_number": batch.batch_number,
        "status": batch.status,
        "total_amount_paise": batch.total_amount_paise,
        "total_records": batch.total_records,
    }, "Payment batch created successfully from run")


# 12. GET /api/v2/payroll/runs/{runId}/payment-batches
@router.get("/runs/{runId}/payment-batches", summary="List payment batches associated with run")
async def list_run_payment_batches(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PaymentBatchService.list_batches(session=db, run_id=runId)
    batches_data = [
        {
            "id": str(b.id),
            "batch_number": b.batch_number,
            "status": b.status,
            "total_amount_paise": b.total_amount_paise,
            "total_records": b.total_records,
            "payment_mode": b.payment_mode,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in res["items"]
    ]
    return _ok(batches_data, "Run payment batches retrieved successfully")


# 13. POST /api/v2/payroll/runs/{runId}/payslips/generate
@router.post("/runs/{runId}/payslips/generate", summary="Trigger batch payslip generation task")
async def generate_run_payslips_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunPayslipGenerateRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    emp_ids = payload.employee_ids if payload else None
    force = payload.force if payload else False
    fmt = payload.format if payload else "pdf"

    job_id = await dispatch_payslip_generation(
        run_id=runId,
        employee_ids=emp_ids,
        force=force,
        format_type=fmt,
    )
    return _ok({"job_id": job_id, "status": "QUEUED"}, "Payslip generation initiated successfully")


# 14. GET /api/v2/payroll/runs/{runId}/preview
@router.get("/runs/{runId}/preview", summary="Preview payroll calculation aggregate summary")
async def preview_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    preview = await PayrollRunService.get_preview(db, run_id=runId)
    return _ok(preview, "Payroll run preview retrieved successfully")


# 15. POST /api/v2/payroll/runs/{runId}/process
@router.post("/runs/{runId}/process", summary="Trigger payroll calculation engine processing")
async def process_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    # Trigger calculation async
    job_id = await dispatch_payroll_processing(run_id=runId)
    return _ok({"job_id": job_id, "status": "PROCESSING"}, "Payroll run processing initiated")


# 16. POST /api/v2/payroll/runs/{runId}/reject
@router.post("/runs/{runId}/reject", summary="Reject payroll run")
async def reject_run_v2(
    runId: uuid.UUID,
    payload: PayrollRunRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    run = await PayrollRunService.reject_run(
        session=db,
        run_id=runId,
        reason=payload.reason,
        comments=payload.comments,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_run_dict(run), "Payroll run rejected")


# 17. POST /api/v2/payroll/runs/{runId}/revalidate
@router.post("/runs/{runId}/revalidate", summary="Revalidate payroll run rules and employee inputs")
async def revalidate_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.revalidate_run(db, run_id=runId)
    return _ok(res, "Payroll run revalidated successfully")


# 18. GET /api/v2/payroll/runs/{runId}/review
@router.get("/runs/{runId}/review", summary="Review payroll run before sign-off")
async def review_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    preview = await PayrollRunService.get_preview(db, run_id=runId)
    val = await PayrollRunService.validate_run(db, run_id=runId)
    return _ok({"summary": preview, "validation": val}, "Payroll run review summary generated")


# 19. POST /api/v2/payroll/runs/{runId}/send-back
@router.post("/runs/{runId}/send-back", summary="Send payroll run back for corrections")
async def send_back_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunSendBackRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    reason = payload.reason if payload else "Sent back for review"
    comments = payload.comments if payload else None
    run = await PayrollRunService.send_back_run(
        session=db,
        run_id=runId,
        reason=reason,
        comments=comments,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(_run_dict(run), "Payroll run sent back successfully")


# 20. POST /api/v2/payroll/runs/{runId}/validate
@router.post("/runs/{runId}/validate", summary="Execute pre-check validation rules on run")
async def validate_run_post_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.validate_run(db, run_id=runId)
    return _ok(res, "Run validation completed")


# 21. GET /api/v2/payroll/runs/{runId}/validation
@router.get("/runs/{runId}/validation", summary="Get validation status of run")
async def get_run_validation_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.validate_run(db, run_id=runId)
    return _ok(res, "Payroll run validation status retrieved successfully")


# 22. GET /api/v2/payroll/runs/{runId}/validation-issues
@router.get("/runs/{runId}/validation-issues", summary="Get list of validation issues found in run")
async def get_run_validation_issues_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.validate_run(db, run_id=runId)
    issues = res.get("issues", [])
    return _ok(issues, "Validation issues retrieved successfully")
