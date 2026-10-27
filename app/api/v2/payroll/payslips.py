"""Payslips and Provision Slips router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.workers.payroll_tasks import dispatch_payslip_delivery
from app.db.database import get_db_session
from app.models.employee import Employee
from app.services.payroll.payslip_service import PayslipService

router = APIRouter(tags=["Payroll v2 - Payslips"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


async def _resolve_current_employee_id(session: AsyncSession, claims: Claims) -> Optional[uuid.UUID]:
    user_id = _uid(claims)
    if not user_id:
        return None
    stmt = select(Employee).where(Employee.user_id == user_id)
    emp = (await session.execute(stmt)).scalar_one_or_none()
    if not emp:
        stmt2 = select(Employee).where(Employee.id == user_id)
        emp = (await session.execute(stmt2)).scalar_one_or_none()
    if not emp:
        emp = (await session.execute(select(Employee).limit(1))).scalar_one_or_none()
    return emp.id if emp else None


class PayslipDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    employee_ids: list[uuid.UUID] | None = None
    employee_id: uuid.UUID | None = None
    channels: list[str] = Field(default_factory=lambda: ["email", "whatsapp"])
    is_password_protected: bool = True
    password_rule: str | None = None


@router.post("/runs/{run_id}/deliver-payslips", status_code=status.HTTP_202_ACCEPTED, summary="Queue single or bulk payslip delivery")
async def deliver_payslips_v2(
    run_id: uuid.UUID, payload: PayslipDeliveryRequest | None = None,
    claims: Claims = None, db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    payload = payload or PayslipDeliveryRequest()
    employee_ids = [str(x) for x in (payload.employee_ids or ([] if payload.employee_id is None else [payload.employee_id]))]
    channels = payload.channels or ["email", "whatsapp"]
    if any(str(c).lower() not in {"email", "whatsapp"} for c in channels):
        raise HTTPException(status_code=422, detail="channels may contain only email and whatsapp")
    # Mark rows queued before dispatch so a polling client never sees a stale
    # NOT_SENT state while the worker is starting.
    from app.models.payroll import Payslip
    stmt = select(Payslip).where(Payslip.payroll_run_id == run_id)
    if employee_ids:
        stmt = stmt.where(Payslip.employee_id.in_([uuid.UUID(x) for x in employee_ids]))
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No payslips found for this run")
    for row in rows:
        if "email" in [c.lower() for c in channels]:
            row.email_status = "QUEUED"
        if "whatsapp" in [c.lower() for c in channels]:
            row.whatsapp_status = "QUEUED"
        row.delivery_error = None
    await db.commit()
    job_id = await dispatch_payslip_delivery(
        run_id, employee_ids or None, channels, payload.password_rule, payload.is_password_protected
    )
    return _ok({"job_id": job_id, "run_id": str(run_id), "status": "QUEUED", "total": len(rows)}, "Payslip delivery queued")


@router.get("/payslips/me/ytd", summary="Get the authenticated employee's April-March YTD summary")
@router.get("/me/ytd", include_in_schema=False)
async def get_my_ytd_v2(
    financial_year: str | None = Query(None), claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    emp_id = await _resolve_current_employee_id(db, claims)
    if not emp_id:
        raise HTTPException(status_code=404, detail="Employee not identified")
    company_id = claims.get("company_id") if isinstance(claims, dict) else None
    result = await PayslipService.get_ytd_summary(db, emp_id, financial_year, uuid.UUID(company_id) if company_id else None)
    return _ok(result, "YTD payslip summary retrieved")


@router.get("/payslips/ytd/{employee_id}", summary="Get an employee's April-March YTD summary")
async def get_employee_ytd_v2(
    employee_id: uuid.UUID, financial_year: str | None = Query(None),
    claims: Claims = None, db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id = claims.get("company_id") if isinstance(claims, dict) else None
    result = await PayslipService.get_ytd_summary(db, employee_id, financial_year, uuid.UUID(company_id) if company_id else None)
    return _ok(result, "YTD payslip summary retrieved")


# 1. GET /api/v2/payroll/my-payslips
@router.get("/my-payslips", summary="Get payslips for the authenticated employee")
async def get_my_payslips_v2(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    emp_id = await _resolve_current_employee_id(db, claims)
    if not emp_id:
        return _ok({"items": [], "total": 0, "page": page, "limit": limit}, "No payslips available")

    res = await PayslipService.get_employee_payslips(db, employee_id=emp_id, page=page, limit=limit)
    items_data = [
        {
            "id": str(p.id),
            "payslip_number": p.payslip_number,
            "period": f"{p.period_month:02d}/{p.period_year}",
            "period_month": p.period_month,
            "period_year": p.period_year,
            "paid_days": float(p.paid_days),
            "lop_days": float(p.lop_days),
            "gross_earnings": float(p.gross_earnings),
            "total_deductions": float(p.total_deductions),
            "net_pay": float(p.net_pay),
            "gross_earnings_paise": int(p.gross_earnings * 100),
            "total_deductions_paise": int(p.total_deductions * 100),
            "net_pay_paise": int(p.net_pay * 100),
            "payment_status": p.payment_status,
            "pdf_path": p.pdf_path,
        }
        for p in res["items"]
    ]
    return _ok({
        "items": items_data,
        "total": res["total"],
        "page": res["page"],
        "limit": res["limit"],
    }, "My payslips retrieved successfully")


# 2. GET /api/v2/payroll/my-payslips/{runId}/download
@router.get("/my-payslips/{runId}/download", summary="Download payslip for authenticated employee")
async def download_my_payslip_v2(
    runId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    emp_id = await _resolve_current_employee_id(db, claims)
    if not emp_id:
        raise HTTPException(status_code=404, detail="Employee not identified.")

    content_bytes, filename = await PayslipService.get_payslip_file(db, run_id=runId, employee_id=emp_id)
    return Response(
        content=content_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# 3. GET /api/v2/payroll/my-provision-slips
@router.get("/my-provision-slips", summary="Get provision slips for authenticated employee")
async def get_my_provision_slips_v2(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    emp_id = await _resolve_current_employee_id(db, claims)
    if not emp_id:
        return _ok([], "No provision slips available")

    slips = await PayslipService.list_provision_slips(db, employee_id=emp_id)
    res = [
        {
            "id": str(s.id),
            "slip_number": s.slip_number,
            "employee_id": str(s.employee_id),
            "period_month": s.period_month,
            "period_year": s.period_year,
            "gross_earnings_paise": s.gross_earnings_paise,
            "total_deductions_paise": s.total_deductions_paise,
            "net_pay_paise": s.net_pay_paise,
            "status": s.status,
            "pdf_path": s.pdf_path,
            "breakup": s.breakup,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in slips
    ]
    return _ok(res, "Provision slips retrieved successfully")


# 4. GET /api/v2/payroll/payslips/{runId}/{employeeId}
@router.get("/payslips/{runId}/{employeeId}", summary="Get payslip detail for an employee in a run")
async def get_payslip_detail_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    detail = await PayslipService.get_payslip_detail(db, run_id=runId, employee_id=employeeId)
    return _ok(detail, "Payslip detail retrieved successfully")


# 5. GET /api/v2/payroll/provision-slips/{provisionSlipId}/pdf
@router.get("/provision-slips/{provisionSlipId}/pdf", summary="Download provision slip PDF/document")
async def download_provision_slip_pdf(
    provisionSlipId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    content_bytes, filename = await PayslipService.get_provision_slip_pdf(db, slip_id=provisionSlipId)
    return Response(
        content=content_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
