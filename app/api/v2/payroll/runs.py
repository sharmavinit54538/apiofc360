"""Payroll Runs router for Payroll v2 (All 22+ Lifecycle Endpoints)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import (
    _is_admin_or_manager,
    _is_payslip_admin_authorized,
    _reject_super_admin,
    _require_admin,
    _require_admin_or_manager,
    _require_payslip_manager_or_admin,
    _require_tenant_id,
    _role,
    _uid,
)
from app.db.database import get_db_session
from app.models.employee import Employee
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
from app.services.payroll.idempotency_service import IdempotencyService, get_optional_idempotency_key
from app.services.payroll.payment_batch_service import PaymentBatchService
from app.services.payroll.payslip_service import PayslipService
from app.services.payroll.parallel_comparison_service import ParallelPayrollComparisonService
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
    # __dict__ defaults keep legacy MagicMock-based API tests and old rows
    # compatible while real ORM runs expose the Batch 7 global-payroll fields.
    fx_rate = r.__dict__.get("fx_rate_to_base", Decimal("1"))
    fx_locked = r.__dict__.get("fx_rate_locked_at")
    return {
        "id": str(r.id),
        "company_id": str(r.company_id) if r.company_id else None,
        "legal_entity_id": str(r.legal_entity_id) if r.legal_entity_id else None,
        "period_id": str(r.period_id) if r.period_id else None,
        "run_number": r.run_number,
        "currency": r.__dict__.get("currency", "INR"),
        "base_currency": r.__dict__.get("base_currency", "INR"),
        "country_code": r.__dict__.get("country_code", "IN"),
        "fx_rate_to_base": str(fx_rate),
        "fx_rate_snapshot": r.__dict__.get("fx_rate_snapshot"),
        "fx_rate_locked_at": fx_locked.isoformat() if fx_locked else None,
        "statutory_rules_snapshot": r.__dict__.get("statutory_rules_snapshot"),
        "statutory_rule_version": r.__dict__.get("statutory_rule_version", "IN_LEGACY_STATUTORY_SERVICE"),
        "total_gross_base_paise": r.__dict__.get("total_gross_base_paise", 0),
        "total_deductions_base_paise": r.__dict__.get("total_deductions_base_paise", 0),
        "total_net_base_paise": r.__dict__.get("total_net_base_paise", 0),
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




def _parallel_comparison_dict(report) -> dict[str, Any]:
    return {
        "id": str(report.id), "report_id": str(report.id), "run_id": str(report.run_id),
        "status": report.status, "summary": report.summary or {},
        "employee_variances": report.employee_variances or [],
        "employees": report.employee_variances or [],
        "head_variances": report.head_variances or {},
        "heads": report.head_variances or {}, "diagnoses": report.diagnoses or [],
        "legacy_file_name": report.legacy_file_name,
        "created_at": report.created_at.isoformat() if report.created_at else None,
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


class PayrollRunCancelRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _optional_claims_company(claims: Claims) -> uuid.UUID | None:
    return _require_tenant_id(claims, allow_super_admin_global=True)


async def _run_status_payload(run: PayrollRun, job_id: Optional[str] = None) -> dict[str, Any]:
    target_job = job_id or getattr(run, "job_id", None)
    job_data = await PayrollJobTracker.get_job(target_job) if target_job else None
    completed_states = ("PROCESSED", "CALCULATED", "PENDING_APPROVAL", "APPROVED", "FINALIZED", "LOCKED", "PAID")
    failed_states = ("FAILED", "CANCELLED")
    if job_data:
        progress = int(job_data.get("progress") or 0)
        job_status = str(job_data.get("status") or "PROCESSING")
    elif run.status in completed_states:
        progress = 100
        job_status = "COMPLETED"
    elif run.status in failed_states:
        progress = 100
        job_status = run.status
    elif run.status == "PROCESSING":
        progress = 25
        job_status = "PROCESSING"
    else:
        progress = 0
        job_status = run.status or "PENDING"

    err_obj = None
    if job_data and job_data.get("error"):
        err_obj = {"message": str(job_data["error"])}
    elif run.status == "FAILED" and isinstance(run.validation_errors, list) and run.validation_errors:
        first_err = run.validation_errors[0]
        if isinstance(first_err, dict):
            err_obj = {
                "code": first_err.get("code"),
                "message": str(first_err.get("detail") or first_err.get("message") or "Payroll calculation failed."),
            }

    total_emp = int(run.total_employees or 0)
    processed_emp = int(job_data.get("processed") or (total_emp if run.status in completed_states else 0)) if job_data else (total_emp if run.status in completed_states else 0)
    return {
        "run_id": str(run.id),
        "period_id": str(run.period_id) if run.period_id else None,
        "status": run.status,
        "run_status": run.status,
        "validation_status": run.validation_status,
        "validation_errors": run.validation_errors,
        "is_locked": run.is_locked,
        "total_employees": total_emp,
        "progress": progress,
        "employees": {
            "total": total_emp,
            "processed": processed_emp,
            "failed": int(job_data.get("failed") or 0) if job_data else (total_emp if run.status == "FAILED" else 0),
        },
        "error": err_obj,
        "job_id": target_job,
        "job": job_data or {
            "status": job_status,
            "progress": progress,
        },
    }


@router.post("/runs", status_code=status.HTTP_201_CREATED, summary="Create a new payroll run")
async def create_run_v2(
    payload: PayrollRunCreateRequest,
    claims: Claims = None,
    idempotency_key: Optional[str] = Depends(get_optional_idempotency_key),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    c_uuid = _optional_claims_company(claims)
    scoped_key = f"create_run:{c_uuid or 'global'}:{idempotency_key}" if idempotency_key else None
    if scoped_key:
        cached = await IdempotencyService.get_cached_result(scoped_key)
        if cached:
            return cached["data"]
        await IdempotencyService.lock_key(scoped_key)

    p_uuid = uuid.UUID(payload.period_id)
    run = await PayrollRunService.create_run(
        session=db,
        period_id=p_uuid,
        company_id=c_uuid,
        user_id=user_id,
        user_role=user_role,
        currency=payload.currency,
        country_code=payload.country_code,
        fx_rate_to_base=payload.fx_rate_to_base,
        fx_rate_source=payload.fx_rate_source,
        fx_rate_as_of=payload.fx_rate_as_of,
        statutory_rules=payload.statutory_rules,
    )
    resp = _ok(_run_dict(run), f"Payroll run created for period {p_uuid}")
    if scoped_key:
        await IdempotencyService.store_result(scoped_key, 201, resp)
    return resp


@router.get("/runs/{runId}", summary="Get payroll run details")
async def get_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId, company_id=_optional_claims_company(claims))
    return _ok(_run_dict(run), "Payroll run details retrieved successfully")


# 1. DELETE /api/v2/payroll/runs/{runId}
@router.delete("/runs/{runId}", summary="Delete draft payroll run")
async def delete_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.delete_run(db, run_id=runId, company_id=_optional_claims_company(claims))
    return _ok(res, "Payroll run deleted successfully")


# 1b. POST /api/v2/payroll/runs/{runId}/cancel - Cancel payroll run (status transition + audit trail)
@router.post("/runs/{runId}/cancel", summary="Cancel payroll run")
async def cancel_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunCancelRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.cancel_run(
        db,
        run_id=runId,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=_optional_claims_company(claims),
        reason=payload.reason if payload else None,
    )
    return _ok(_run_dict(run), "Payroll run cancelled successfully")


# 1c. GET /api/v2/payroll/runs/{runId}/status - Live payroll run status
@router.get("/runs/{runId}/status", summary="Get live payroll run status and async job progress")
async def get_run_status_v2(
    runId: uuid.UUID,
    job_id: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId, company_id=_optional_claims_company(claims))
    return _ok(await _run_status_payload(run, job_id=job_id), "Payroll run status retrieved successfully")


# 1d. POST /api/v2/payroll/runs/{runId}/retry - Retry failed payroll run
@router.post("/runs/{runId}/retry", summary="Retry failed payroll run")
async def retry_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    idempotency_key: Optional[str] = Depends(get_optional_idempotency_key),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    c_uuid = _optional_claims_company(claims)
    scoped_key = f"retry_run:{c_uuid or 'global'}:{runId}:{idempotency_key}" if idempotency_key else None
    if scoped_key:
        cached = await IdempotencyService.get_cached_result(scoped_key)
        if cached:
            return cached["data"]
        await IdempotencyService.lock_key(scoped_key)

    run = await PayrollRunService.retry_run(
        db,
        run_id=runId,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    resp = _ok(_run_dict(run), "Payroll run retry executed successfully")
    if scoped_key:
        await IdempotencyService.store_result(scoped_key, 200, resp)
    return resp


# 1e. POST /api/v2/payroll/runs/{runId}/recalculate - Recalculate uncommitted run
@router.post("/runs/{runId}/recalculate", summary="Recalculate uncommitted payroll run")
async def recalculate_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    idempotency_key: Optional[str] = Depends(get_optional_idempotency_key),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    c_uuid = _optional_claims_company(claims)
    scoped_key = f"recalc_run:{c_uuid or 'global'}:{runId}:{idempotency_key}" if idempotency_key else None
    if scoped_key:
        cached = await IdempotencyService.get_cached_result(scoped_key)
        if cached:
            return cached["data"]
        await IdempotencyService.lock_key(scoped_key)

    run = await PayrollRunService.recalculate_run(
        db,
        run_id=runId,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    resp = _ok(_run_dict(run), "Payroll run recalculated successfully")
    if scoped_key:
        await IdempotencyService.store_result(scoped_key, 200, resp)
    return resp


# 2. GET /api/v2/payroll/runs/{runId}/approval
@router.get("/runs/{runId}/approval", summary="Get approval status and details for payroll run")
async def get_run_approval_details(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId, company_id=_optional_claims_company(claims))
    return _ok({
        "run_id": str(run.id),
        "period_id": str(run.period_id) if run.period_id else None,
        "period_month": run.period_month,
        "period_year": run.period_year,
        "status": run.status,
        "is_approved": run.status in ("APPROVED", "FINALIZED", "LOCKED", "PAID"),
        "approved_by": str(run.approved_by) if run.approved_by else None,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "comments": run.comments,
        "rejection_reason": run.rejection_reason,
        "total_employees": run.total_employees,
        "total_gross_paise": run.total_gross_paise,
        "total_deductions_paise": run.total_deductions_paise,
        "total_net_paise": run.total_net_paise,
        "total_gross": float(run.total_gross or 0),
        "total_deductions": float(run.total_deductions or 0),
        "total_net": float(run.total_net or 0),
        "validation_status": run.validation_status,
        "validation_errors": run.validation_errors,
    }, "Approval status retrieved successfully")


# 3. POST /api/v2/payroll/runs/{runId}/approve
@router.post("/runs/{runId}/approve", summary="Approve payroll run")
async def approve_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunApproveRequest] = None,
    claims: Claims = None,
    idempotency_key: Optional[str] = Depends(get_optional_idempotency_key),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    c_uuid = _optional_claims_company(claims)
    scoped_key = f"approve_run:{c_uuid or 'global'}:{runId}:{idempotency_key}" if idempotency_key else None
    if scoped_key:
        cached = await IdempotencyService.get_cached_result(scoped_key)
        if cached:
            return cached["data"]
        await IdempotencyService.lock_key(scoped_key)

    comments = payload.comments if payload else None
    run = await PayrollRunService.approve_run(
        session=db,
        run_id=runId,
        comments=comments,
        user_id=user_id,
        user_role=user_role,
        company_id=c_uuid,
    )
    resp = _ok(_run_dict(run), "Payroll run approved successfully")
    if scoped_key:
        await IdempotencyService.store_result(scoped_key, 200, resp)
    return resp


async def _authorize_employee_payslip_access(
    db: AsyncSession,
    claims: Claims,
    employee_id: uuid.UUID,
    action_label: str = "payslip",
) -> uuid.UUID | None:
    c_uuid = _optional_claims_company(claims)
    if await _is_payslip_admin_authorized(db, claims, c_uuid):
        return c_uuid
    user_id = _uid(claims)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: You can only view your own {action_label}.",
        )
    stmt = select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False)  # noqa: E712
    if c_uuid is not None:
        stmt = stmt.where(Employee.company_id == c_uuid)
    caller_emp = (await db.execute(stmt)).scalar_one_or_none()
    if not caller_emp:
        stmt2 = select(Employee).where(Employee.id == user_id, Employee.is_deleted == False)  # noqa: E712
        if c_uuid is not None:
            stmt2 = stmt2.where(Employee.company_id == c_uuid)
        caller_emp = (await db.execute(stmt2)).scalar_one_or_none()
    if not caller_emp or caller_emp.id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: You can only view your own {action_label}.",
        )
    return c_uuid


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
        company_id=_optional_claims_company(claims),
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
    res = await PayrollRunService.get_run_employee(
        db,
        run_id=runId,
        employee_id=employeeId,
        company_id=_optional_claims_company(claims),
    )
    return _ok(res, "Employee run breakdown retrieved successfully")


# 6. GET /api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip
@router.get("/runs/{runId}/employees/{employeeId}/payslip", summary="Get payslip JSON breakdown for employee in run")
async def get_run_employee_payslip_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = await _authorize_employee_payslip_access(db, claims, employeeId, action_label="payslip")
    res = await PayslipService.get_payslip_detail(db, run_id=runId, employee_id=employeeId, company_id=c_uuid)
    return _ok(res, "Employee payslip retrieved successfully")


# 7. GET /api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip/download
@router.get("/runs/{runId}/employees/{employeeId}/payslip/download", summary="Download payslip document for employee in run")
async def download_run_employee_payslip_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    inline: bool = Query(False),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    from app.models.payroll import Payslip

    c_uuid = await _authorize_employee_payslip_access(db, claims, employeeId, action_label="payslip")
    content_bytes, filename = await PayslipService.get_payslip_file(
        db,
        run_id=runId,
        employee_id=employeeId,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
    )
    ps = (
        await db.execute(
            select(Payslip).where(Payslip.payroll_run_id == runId, Payslip.employee_id == employeeId)
        )
    ).scalar_one_or_none()
    if ps is not None:
        ps.download_count = (ps.download_count or 0) + 1
        await db.commit()
    disposition = "inline" if inline else "attachment"
    return Response(
        content=content_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


# 8. GET /api/v2/payroll/runs/{runId}/finalization
@router.get("/runs/{runId}/finalization", summary="Get finalization summary and lock status for run")
async def get_run_finalization_summary(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId, company_id=_optional_claims_company(claims))
    return _ok({
        "run_id": str(run.id),
        "period_id": str(run.period_id) if run.period_id else None,
        "status": run.status,
        "is_finalized": run.status in ("FINALIZED", "LOCKED", "PAID"),
        "is_locked": run.is_locked,
        "finalized_by": str(run.finalized_by) if run.finalized_by else None,
        "finalized_at": run.finalized_at.isoformat() if run.finalized_at else None,
        "total_employees": run.total_employees,
        "total_gross_paise": run.total_gross_paise,
        "total_deductions_paise": run.total_deductions_paise,
        "total_net_paise": run.total_net_paise,
        "notes": run.notes,
    }, "Finalization summary retrieved successfully")


# 9. POST /api/v2/payroll/runs/{runId}/finalize
@router.post("/runs/{runId}/finalize", summary="Finalize payroll run")
async def finalize_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunFinalizeRequest] = None,
    claims: Claims = None,
    idempotency_key: Optional[str] = Depends(get_optional_idempotency_key),
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    c_uuid = _optional_claims_company(claims)
    scoped_key = f"finalize_run:{c_uuid or 'global'}:{runId}:{idempotency_key}" if idempotency_key else None
    if scoped_key:
        cached = await IdempotencyService.get_cached_result(scoped_key)
        if cached:
            return cached["data"]
        await IdempotencyService.lock_key(scoped_key)

    notes = payload.notes if payload else None
    lock = payload.lock if payload else True
    run = await PayrollRunService.finalize_run(
        session=db,
        run_id=runId,
        notes=notes,
        lock=lock,
        user_id=user_id,
        user_role=user_role,
        company_id=c_uuid,
    )
    resp = _ok(_run_dict(run), "Payroll run finalized successfully")
    if scoped_key:
        await IdempotencyService.store_result(scoped_key, 200, resp)
    return resp


# 10. GET /api/v2/payroll/runs/{runId}/generation-status
@router.get("/runs/{runId}/generation-status", summary="Poll async generation/calculation status")
async def get_run_generation_status(
    runId: uuid.UUID,
    job_id: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.get_run(db, runId, company_id=_optional_claims_company(claims))
    return _ok(await _run_status_payload(run, job_id=job_id), "Generation status retrieved successfully")


# 11. POST /api/v2/payroll/runs/{runId}/payment-batches
@router.post("/runs/{runId}/payment-batches", status_code=status.HTTP_201_CREATED, summary="Create payment batch from run")
async def create_payment_batch_from_run(
    runId: uuid.UUID,
    payload: PayrollRunPaymentBatchCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    _reject_super_admin(claims)
    c_uuid = _require_tenant_id(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    try:
        src_uuid = uuid.UUID(str(payload.source_account_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid source bank account ID.") from exc
    batch = await PaymentBatchService.create_batch_from_run(
        session=db,
        run_id=runId,
        source_account_id=str(src_uuid),
        payment_mode=payload.payment_mode,
        held_employee_ids=payload.held_employee_ids,
        notes=payload.notes,
        user_id=user_id,
        user_role=user_role,
        company_id=c_uuid,
        payment_date=payload.payment_date,
        validate_source_account=True,
    )
    ctx = await PaymentBatchService.build_batch_contexts(db, [batch])
    return _ok(PaymentBatchService.serialize_batch(batch, ctx), "Payment batch created successfully from run")


# 12. GET /api/v2/payroll/runs/{runId}/payment-batches
@router.get("/runs/{runId}/payment-batches", summary="List payment batches associated with run")
async def list_run_payment_batches(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    _reject_super_admin(claims)
    c_uuid = _require_tenant_id(claims)
    await PayrollRunService.get_run(db, runId, company_id=c_uuid)
    res = await PaymentBatchService.list_batches(session=db, company_id=c_uuid, run_id=runId)
    ctx = await PaymentBatchService.build_batch_contexts(db, res["items"])
    batches_data = [PaymentBatchService.serialize_batch(b, ctx) for b in res["items"]]
    return _ok(batches_data, "Run payment batches retrieved successfully")


# 13. POST /api/v2/payroll/runs/{runId}/payslips/generate
@router.post("/runs/{runId}/payslips/generate", summary="Trigger batch payslip generation task")
async def generate_run_payslips_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunPayslipGenerateRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    from app.services.payroll.payslip_service import FINALIZED_RUN_STATUSES

    c_uuid = _optional_claims_company(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    run = await PayrollRunService.get_run(db, runId, company_id=c_uuid)
    allow_draft = bool(payload and payload.allow_draft)
    if not allow_draft and str(run.status or "").upper() not in FINALIZED_RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Official payslip generation requires an approved or finalized payroll run (current: {run.status}).",
        )
    emp_ids = payload.employee_ids if payload else None
    force = payload.force if payload else False
    fmt = payload.format if payload else "pdf"

    job_id = await dispatch_payslip_generation(
        run_id=runId,
        employee_ids=emp_ids,
        force=force,
        format_type=fmt,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
        require_finalized=not allow_draft,
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
    preview = await PayrollRunService.get_preview(db, run_id=runId, company_id=_optional_claims_company(claims))
    return _ok(preview, "Payroll run preview retrieved successfully")


@router.post("/runs/{run_id}/parallel-compare", summary="Compare a payroll run with legacy CSV/XLSX output")
async def parallel_compare_run_v2(
    run_id: uuid.UUID,
    file: Optional[UploadFile] = File(None),
    legacy_file: Optional[UploadFile] = File(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    upload = file or legacy_file
    if upload is None:
        raise HTTPException(status_code=422, detail="A legacy CSV or XLSX file is required (field 'file').")
    company_id = uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None
    report = await ParallelPayrollComparisonService.compare_file(
        db, run_id=run_id, file=upload, company_id=company_id, created_by=_uid(claims)
    )
    return _ok(_parallel_comparison_dict(report), "Parallel payroll comparison generated and persisted")


# 15. POST /api/v2/payroll/runs/{runId}/process
@router.post("/runs/{runId}/process", summary="Trigger payroll calculation engine processing")
async def process_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id = uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None
    await PayrollRunService.get_run(db, runId, company_id=company_id)
    job_id = await dispatch_payroll_processing(run_id=runId, company_id=company_id)
    return _ok({"job_id": job_id, "status": "PROCESSING"}, "Payroll run processing initiated")


# 15b. POST /api/v2/payroll/runs/{runId}/calculate
@router.post("/runs/{runId}/calculate", summary="Synchronously execute payroll calculation engine")
async def calculate_run_sync_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.execute_run_calculation(
        db, run_id=runId, user_id=_uid(claims), user_role=_role(claims),
        company_id=uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None,
    )
    return _ok(_run_dict(run), "Payroll calculation executed successfully")


@router.post("/runs/{runId}/submit-for-approval", summary="Submit a processed run for approval")
@router.post("/runs/{runId}/submit", summary="Submit a processed run for approval (alias)")
async def submit_run_for_approval_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.submit_for_approval(
        db, runId, user_id=_uid(claims), user_role=_role(claims),
        company_id=uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None,
    )
    return _ok(_run_dict(run), "Payroll run submitted for approval")


@router.post("/runs/{runId}/lock", summary="Lock an approved payroll run")
async def lock_run_v2(
    runId: uuid.UUID,
    payload: Optional[PayrollRunFinalizeRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.finalize_run(
        db, runId, notes=payload.notes if payload else None, lock=True,
        user_id=_uid(claims), user_role=_role(claims),
        company_id=uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None,
    )
    return _ok(_run_dict(run), "Payroll run locked successfully")


@router.post("/runs/{runId}/mark-paid", summary="Mark a locked payroll run as paid")
@router.post("/runs/{runId}/pay", summary="Mark a locked payroll run as paid (alias)")
async def mark_run_paid_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    run = await PayrollRunService.mark_paid(
        db, runId, user_id=_uid(claims), user_role=_role(claims),
        company_id=uuid.UUID(claims["company_id"]) if claims and claims.get("company_id") else None,
    )
    return _ok(_run_dict(run), "Payroll run marked as paid")


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
        company_id=_optional_claims_company(claims),
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
    res = await PayrollRunService.revalidate_run(db, run_id=runId, company_id=_optional_claims_company(claims))
    return _ok(res, "Payroll run revalidated successfully")


# 18. GET /api/v2/payroll/runs/{runId}/review
@router.get("/runs/{runId}/review", summary="Review payroll run before sign-off")
async def review_run_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    c_uuid = _optional_claims_company(claims)
    preview = await PayrollRunService.get_preview(db, run_id=runId, company_id=c_uuid)
    val = await PayrollRunService.validate_run(db, run_id=runId, company_id=c_uuid)
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
        company_id=_optional_claims_company(claims),
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
    res = await PayrollRunService.validate_run(db, run_id=runId, company_id=_optional_claims_company(claims))
    return _ok(res, "Run validation completed")


# 21. GET /api/v2/payroll/runs/{runId}/validation
@router.get("/runs/{runId}/validation", summary="Get validation status of run")
async def get_run_validation_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.validate_run(db, run_id=runId, company_id=_optional_claims_company(claims))
    return _ok(res, "Payroll run validation status retrieved successfully")


# 22. GET /api/v2/payroll/runs/{runId}/validation-issues
@router.get("/runs/{runId}/validation-issues", summary="Get list of validation issues found in run")
async def get_run_validation_issues_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayrollRunService.validate_run(db, run_id=runId, company_id=_optional_claims_company(claims))
    issues = res.get("issues", [])
    return _ok(issues, "Validation issues retrieved successfully")


class EntityPayrollCalendarRequest(BaseModel):
    period_month: int = Field(ge=1, le=12)
    period_year: int = Field(ge=2000, le=2200)
    start_date: date
    end_date: date
    processing_date: date
    pay_date: date
    attendance_cutoff_date: date | None = None


class EmployeeEntityTransferRequest(BaseModel):
    employee_id: uuid.UUID
    to_legal_entity_id: uuid.UUID
    to_branch_id: uuid.UUID | None = None
    effective_date: date
    reason: str = Field(min_length=3)


def _claims_company(claims: dict) -> uuid.UUID:
    value = claims.get("company_id") if claims else None
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required")
    return uuid.UUID(str(value))


@router.post("/entities/{legal_entity_id}/calendar", summary="Create/update an entity-specific payroll calendar")
async def upsert_entity_calendar(
    legal_entity_id: uuid.UUID, payload: EntityPayrollCalendarRequest,
    claims: Claims = None, db: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    try:
        calendar, period = await PayrollRunService.upsert_entity_payroll_calendar(
            db, legal_entity_id=legal_entity_id, company_id=_claims_company(claims), **payload.model_dump(),
        )
        return _ok({
            "calendar_id": str(calendar.id), "payroll_period_id": str(period.id),
            "legal_entity_id": str(calendar.legal_entity_id), "status": calendar.status,
            "start_date": calendar.start_date.isoformat(), "end_date": calendar.end_date.isoformat(),
            "pay_date": calendar.pay_date.isoformat(),
        }, "Entity payroll calendar saved")
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc)) from exc


@router.post("/entities/transfers", summary="Schedule or complete an inter-entity employee transfer")
async def transfer_employee_entity(
    payload: EmployeeEntityTransferRequest, claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    try:
        transfer = await PayrollRunService.transfer_employee(
            db, employee_id=payload.employee_id, to_legal_entity_id=payload.to_legal_entity_id,
            to_branch_id=payload.to_branch_id, effective_date=payload.effective_date,
            reason=payload.reason, requested_by=_uid(claims), company_id=_claims_company(claims),
        )
        return _ok({
            "transfer_id": str(transfer.id), "status": transfer.status,
            "effective_date": transfer.effective_date.isoformat(),
            "from_legal_entity_id": str(transfer.from_legal_entity_id) if transfer.from_legal_entity_id else None,
            "to_legal_entity_id": str(transfer.to_legal_entity_id),
        }, "Employee entity transfer recorded")
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc)) from exc


@router.post("/entities/transfers/process-due", summary="Complete all effective-dated employee transfers")
async def process_entity_transfers(claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin(claims)
    count = await PayrollRunService.process_due_entity_transfers(db, company_id=_claims_company(claims))
    return _ok({"completed": count}, "Due employee entity transfers processed")
