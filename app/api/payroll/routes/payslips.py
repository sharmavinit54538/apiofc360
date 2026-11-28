"""Route handlers for Payslip queries, generation, preview, PDF export, bulk operations, and audit logs — Enterprise Database-Driven."""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Response, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.exceptions import NotFoundException
from app.api.payroll.permissions import (
    _is_payslip_admin_authorized,
    _require_payslip_manager_or_admin,
    _require_tenant_id,
    _role,
    _uid,
)
from app.api.payroll.responses import success_response
from app.api.payroll.serializers import _payslip_dict
from app.models.employee import Employee
from app.models.payroll import PayrollAuditLog, PayrollRun, Payslip
from app.schemas.auth import APIResponse
from app.services.payroll.payslip_service import FINALIZED_RUN_STATUSES, PayslipService

logger = logging.getLogger(__name__)

router = APIRouter()

_PRIVATE_PDF_HEADERS = {
    "Cache-Control": "private, no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/payslips", response_model=APIResponse[dict], summary="List payslips")
@router.get("/admin/payslips", response_model=APIResponse[dict], summary="List admin payslips")
@router.head("/payslips")
@router.head("/admin/payslips")
async def list_payslips(
    claims: Claims = None,
    db: DB = None,
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    designation: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    employment_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: Optional[int] = Query(20, ge=1, le=100),
    page_size: Optional[int] = Query(None),
    sort_by: Optional[str] = Query("created_at"),
    sort_dir: Optional[str] = Query("desc"),
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)

    effective_limit = page_size if isinstance(page_size, int) else (limit if isinstance(limit, int) else 20)
    effective_page = page if isinstance(page, int) else 1

    stmt = (
        select(Payslip)
        .join(Employee, Payslip.employee_id == Employee.id)
        .options(selectinload(Payslip.employee))
        .where(
            Employee.is_deleted == False,  # noqa: E712
            Payslip.company_id == c_uuid,
        )
    )

    if search and search.strip():
        s = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Employee.first_name).like(s),
                func.lower(Employee.last_name).like(s),
                func.lower(Employee.employee_id).like(s),
                func.lower(Employee.company_email).like(s),
                func.lower(Employee.personal_email).like(s),
                func.lower(Payslip.payslip_number).like(s),
            )
        )

    if department and department != "all":
        stmt = stmt.where(func.lower(Employee.department) == department.lower())
    if designation and designation != "all":
        stmt = stmt.where(func.lower(Employee.designation) == designation.lower())
    if location and location != "all":
        stmt = stmt.where(
            or_(
                func.lower(Employee.work_location) == location.lower(),
                func.lower(Employee.branch) == location.lower(),
            )
        )
    if month and month > 0:
        stmt = stmt.where(Payslip.period_month == month)
    if year and year > 0:
        stmt = stmt.where(Payslip.period_year == year)
    if status and status != "all":
        if status.upper() == "GENERATED":
            stmt = stmt.where(Payslip.generated_at.isnot(None))
        elif status.upper() == "PENDING":
            stmt = stmt.where(Payslip.generated_at.is_(None))
        else:
            stmt = stmt.where(func.upper(Payslip.status) == status.upper())
    if payment_status and payment_status != "all":
        stmt = stmt.where(func.upper(Payslip.payment_status) == payment_status.upper())
    if employment_type and employment_type != "all":
        stmt = stmt.where(func.lower(Employee.employment_type) == employment_type.lower())

    if sort_by == "period_month":
        order_col = Payslip.period_month
    elif sort_by == "net_pay":
        order_col = Payslip.net_pay
    elif sort_by == "employee_name":
        order_col = Employee.first_name
    else:
        order_col = Payslip.created_at

    stmt = stmt.order_by(order_col.asc() if sort_dir == "asc" else order_col.desc())

    total_items = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    offset = (effective_page - 1) * effective_limit
    payslips = list((await db.execute(stmt.offset(offset).limit(effective_limit))).scalars().all())

    summary_stmt = select(
        func.count(Payslip.id),
        func.sum(Payslip.net_pay),
        func.avg(Payslip.net_pay),
    ).where(Payslip.company_id == c_uuid)
    sum_res = (await db.execute(summary_stmt)).fetchone()
    total_payslips = sum_res[0] if sum_res else 0
    total_amount = float(sum_res[1] or 0) if sum_res else 0.0
    avg_amount = float(sum_res[2] or 0) if sum_res else 0.0

    items_data = [_payslip_dict(p) for p in payslips]
    total_pages = max(1, (total_items + effective_limit - 1) // effective_limit)

    summary_data = {
        "total_payslips": total_payslips,
        "generated": sum(1 for p in payslips if p.generated_at),
        "pending_generation": sum(1 for p in payslips if not p.generated_at),
        "sent": sum(1 for p in payslips if p.email_status == "SENT"),
        "downloaded": sum(1 for p in payslips if (p.download_count or 0) > 0),
        "failed": sum(1 for p in payslips if p.email_status == "FAILED"),
        "total_payroll_amount": total_amount,
        "average_net_salary": avg_amount,
    }

    return success_response(
        {
            "summary": summary_data,
            "items": items_data,
            "pagination": {
                "page": effective_page,
                "limit": effective_limit,
                "total": total_items,
                "totalPages": total_pages,
            },
        },
        "Payslips list retrieved successfully.",
    )


@router.get("/payslips/{payslip_id}/preview", response_model=APIResponse[dict], summary="Get single payslip preview data")
async def get_payslip_preview(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    payload = await PayslipService.get_payslip_preview(db, payslip_id, company_id=c_uuid)
    return success_response(payload, "Payslip preview payload retrieved.")


@router.post("/payslips/bulk-generate", response_model=APIResponse[dict], summary="Bulk generate payslips from a finalized payroll run")
async def bulk_generate_payslips(
    claims: Claims = None,
    db: DB = None,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)

    run_id_raw = body.get("run_id") or body.get("payroll_run_id")
    target_run: PayrollRun | None = None
    if run_id_raw:
        target_run = (
            await db.execute(
                select(PayrollRun).where(
                    PayrollRun.id == uuid.UUID(str(run_id_raw)),
                    PayrollRun.company_id == c_uuid,
                )
            )
        ).scalar_one_or_none()
    else:
        month = int(body.get("month", datetime.now(timezone.utc).month))
        year = int(body.get("year", datetime.now(timezone.utc).year))
        target_run = (
            await db.execute(
                select(PayrollRun)
                .where(
                    PayrollRun.company_id == c_uuid,
                    PayrollRun.period_month == month,
                    PayrollRun.period_year == year,
                )
                .order_by(desc(PayrollRun.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()

    if not target_run:
        raise NotFoundException("Payroll run not found for this period and organization.")

    allow_draft = bool(body.get("allow_draft", False))
    if not allow_draft and str(target_run.status or "").upper() not in FINALIZED_RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Official bulk payslip generation requires an approved or finalized payroll run (current: {target_run.status}).",
        )

    emp_ids = [str(x) for x in (body.get("employee_ids") or []) if x] or None
    generated_count = await PayslipService.generate_batch_payslips(
        db,
        target_run.id,
        employee_ids=emp_ids,
        force=bool(body.get("force", False)),
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
        require_finalized=not allow_draft,
        release=str(target_run.status or "").upper() in FINALIZED_RUN_STATUSES,
    )
    rows = list(
        (
            await db.execute(
                select(Payslip).where(Payslip.payroll_run_id == target_run.id, Payslip.company_id == c_uuid)
            )
        ).scalars().all()
    )
    return success_response(
        {
            "run_id": str(target_run.id),
            "generated_count": generated_count,
            "payslip_ids": [str(p.id) for p in rows],
        },
        f"Successfully generated {generated_count} payslip document(s).",
    )


@router.post("/payslips/bulk-email", response_model=APIResponse[dict], summary="Bulk email payslips")
async def bulk_email_payslips(
    claims: Claims = None,
    db: DB = None,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    payslip_ids = body.get("payslip_ids", [])
    if not payslip_ids:
        return success_response({"sent_count": 0, "failed_count": 0}, "No payslips specified for email dispatch.")

    valid_uuids = [uuid.UUID(str(i)) for i in payslip_ids if i]
    rows = list(
        (await db.execute(select(Payslip).where(Payslip.id.in_(valid_uuids), Payslip.company_id == c_uuid))).scalars().all()
    )
    by_run: dict[uuid.UUID, list[str]] = {}
    for p in rows:
        by_run.setdefault(p.payroll_run_id, []).append(str(p.employee_id))

    sent_count = 0
    failed_count = 0
    for run_id, emp_ids in by_run.items():
        res = await PayslipService.deliver_payslips(
            db,
            run_id,
            employee_ids=emp_ids,
            channels=["email"],
            is_password_protected=bool(body.get("is_password_protected", True)),
            company_id=c_uuid,
        )
        sent_count += max(0, int(res["total"]) - int(res["failed"]))
        failed_count += int(res["failed"])

    return success_response(
        {"sent_count": sent_count, "failed_count": failed_count},
        f"Payslips emailed: {sent_count} succeeded, {failed_count} failed.",
    )


@router.post("/payslips/bulk-download", summary="Bulk download payslips ZIP")
async def bulk_download_payslips(
    claims: Claims = None,
    db: DB = None,
    body: dict = Body(default={}),
) -> Response:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    payslip_ids = body.get("payslip_ids", [])
    if not payslip_ids:
        return Response(content=b"", media_type="application/zip", status_code=400)

    valid_uuids = [uuid.UUID(str(i)) for i in payslip_ids if i]
    payslips = list(
        (
            await db.execute(
                select(Payslip)
                .where(Payslip.id.in_(valid_uuids), Payslip.company_id == c_uuid)
                .options(selectinload(Payslip.employee))
            )
        ).scalars().all()
    )
    if not payslips:
        raise NotFoundException("No payslips found for your organization.")

    ctx = await PayslipService._load_bulk_context(db, payslips)
    actor_id = _uid(claims)
    actor_role = _role(claims)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for p in payslips:
            pdf_bytes, filename, _, _ = await PayslipService.generate_and_store_payslip(
                db,
                payslip_id=p.id,
                company_id=c_uuid,
                actor_id=actor_id,
                actor_role=actor_role,
                ctx=ctx,
            )
            zip_file.writestr(filename, pdf_bytes)
            p.download_count = (p.download_count or 0) + 1

    await db.commit()
    zip_buffer.seek(0)

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            **_PRIVATE_PDF_HEADERS,
            "Content-Disposition": f'attachment; filename="payslips_bundle_{datetime.now(timezone.utc).strftime("%Y%m%d")}.zip"',
        },
    )


@router.get("/payslips/{payslip_id}/pdf", summary="Download single payslip PDF")
async def download_payslip_pdf(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> Response:
    c_uuid = _require_tenant_id(claims)
    stmt = (
        select(Payslip)
        .where(Payslip.id == payslip_id, Payslip.company_id == c_uuid)
        .options(selectinload(Payslip.employee))
    )
    p = (await db.execute(stmt)).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payslip Not Found")

    if not await _is_payslip_admin_authorized(db, claims, c_uuid):
        caller_uid = _uid(claims)
        emp = (
            await db.execute(
                select(Employee).where(
                    Employee.user_id == caller_uid,
                    Employee.company_id == c_uuid,
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none() if caller_uid else None
        if not emp or emp.id != p.employee_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You can only download your own payslip.",
            )

    pdf_bytes, filename, updated_ps, _ = await PayslipService.generate_and_store_payslip(
        db,
        payslip_id=p.id,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
    )
    if bool(updated_ps.is_password_protected):
        emp = p.employee or await db.get(Employee, p.employee_id)
        if emp is not None:
            pdf_bytes, _ = await asyncio.to_thread(
                PayslipService.protect_pdf, pdf_bytes, emp, updated_ps, updated_ps.password_rule
            )

    updated_ps.download_count = (updated_ps.download_count or 0) + 1
    await db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            **_PRIVATE_PDF_HEADERS,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/payslips/{payslip_id}/email", response_model=APIResponse[dict], summary="Email single payslip")
async def email_single_payslip(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    p = (await db.execute(select(Payslip).where(Payslip.id == payslip_id, Payslip.company_id == c_uuid))).scalar_one_or_none()
    if not p:
        raise NotFoundException("Payslip not found.")

    res = await PayslipService.deliver_payslips(
        db,
        p.payroll_run_id,
        employee_ids=[str(p.employee_id)],
        channels=["email"],
        company_id=c_uuid,
    )
    item = (res.get("items") or [{}])[0]
    sent = item.get("email_status") == "SENT"
    return success_response({"sent": sent, **item}, "Payslip emailed successfully." if sent else "Payslip email dispatch completed with warnings.")


@router.post("/payslips/{payslip_id}/regenerate", response_model=APIResponse[dict], summary="Regenerate single payslip")
async def regenerate_single_payslip(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    _, _, ps, _ = await PayslipService.generate_and_store_payslip(
        db,
        payslip_id=payslip_id,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
        force=True,
    )
    ps_loaded = (
        await db.execute(select(Payslip).where(Payslip.id == ps.id).options(selectinload(Payslip.employee)))
    ).scalar_one()
    return success_response(_payslip_dict(ps_loaded), "Payslip regenerated successfully.")


@router.delete("/payslips/{payslip_id}", response_model=APIResponse[dict], summary="Delete payslip")
async def delete_payslip(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    p = (await db.execute(select(Payslip).where(Payslip.id == payslip_id, Payslip.company_id == c_uuid))).scalar_one_or_none()
    if not p:
        raise NotFoundException("Payslip not found.")

    await db.delete(p)
    await db.commit()
    return success_response({"deleted": True}, "Payslip record deleted successfully.")


@router.get("/payslips/{payslip_id}/audit-logs", response_model=APIResponse[dict], summary="Get audit logs for payslip")
async def get_payslip_audit_logs(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    p = (await db.execute(select(Payslip).where(Payslip.id == payslip_id, Payslip.company_id == c_uuid))).scalar_one_or_none()
    if not p:
        raise NotFoundException("Payslip not found.")

    audit_rows = list(
        (
            await db.execute(
                select(PayrollAuditLog)
                .where(
                    PayrollAuditLog.company_id == c_uuid,
                    PayrollAuditLog.entity_id == p.id,
                )
                .order_by(desc(PayrollAuditLog.created_at))
            )
        ).scalars().all()
    )
    logs = [
        {
            "id": str(row.id),
            "activity": row.action,
            "performed_by": str(row.actor_id) if row.actor_id else "System Payroll Engine",
            "role": row.actor_role or "System",
            "timestamp": row.created_at.isoformat() if row.created_at else None,
            "details": row.reason or "",
            "before_status": row.before_status,
            "after_status": row.after_status,
        }
        for row in audit_rows
    ]
    return success_response({"items": logs}, "Audit logs retrieved successfully.")


@router.get("/payslips/{payslip_id}", response_model=APIResponse[dict], summary="Get single payslip")
async def get_payslip(
    payslip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    c_uuid = _require_tenant_id(claims)
    p = (
        await db.execute(
            select(Payslip)
            .where(Payslip.id == payslip_id, Payslip.company_id == c_uuid)
            .options(selectinload(Payslip.employee))
        )
    ).scalar_one_or_none()
    if not p:
        raise NotFoundException("Payslip not found.")

    if not await _is_payslip_admin_authorized(db, claims, c_uuid):
        user_id = _uid(claims)
        emp = (
            await db.execute(
                select(Employee).where(
                    Employee.user_id == user_id,
                    Employee.company_id == c_uuid,
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
        ).scalar_one_or_none()
        if not emp or emp.id != p.employee_id:
            raise HTTPException(status_code=403, detail="Forbidden: You can only view your own payslip.")

    return success_response(_payslip_dict(p), "Payslip details retrieved.")
