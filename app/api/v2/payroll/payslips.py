"""Payslips and Provision Slips router for Payroll v2 (Enterprise Edition)."""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.payroll.constants import ADMIN_ROLES
from app.api.payroll.dependencies import Claims, OptionalClaims
from app.api.payroll.permissions import (
    _is_payslip_admin_authorized,
    _reject_super_admin,
    _require_payslip_manager_or_admin,
    _require_tenant_id,
    _role,
    _uid,
)
from app.db.database import get_db_session
from app.models.employee import Employee
from app.models.payroll import PayrollAuditLog, PayrollRun, Payslip, PayslipDocument
from app.models.user.role import RoleEnum
from app.services.payroll.payslip_service import FINALIZED_RUN_STATUSES, PayslipService
from app.services.payroll.payslip_settings_service import PayslipSettingsService
from app.workers.payroll_tasks import dispatch_payslip_delivery, dispatch_payslip_generation

router = APIRouter(tags=["Payroll v2 - Payslips"])

_PDF_SECURITY_HEADERS_BASE = {
    "Cache-Control": "private, no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _pdf_response(content_bytes: bytes, filename: str, *, inline: bool = False) -> Response:
    disposition = "inline" if inline else "attachment"
    headers = {
        **_PDF_SECURITY_HEADERS_BASE,
        "Content-Disposition": f'{disposition}; filename="{filename}"',
    }
    return Response(content=content_bytes, media_type="application/pdf", headers=headers)


async def _resolve_current_employee_id(
    session: AsyncSession,
    claims: Claims,
    company_id: Optional[uuid.UUID] = None,
) -> Optional[uuid.UUID]:
    user_id = _uid(claims)
    if not user_id:
        return None
    c_uuid = company_id
    if c_uuid is None and isinstance(claims, dict) and claims.get("company_id"):
        try:
            c_uuid = uuid.UUID(str(claims["company_id"]))
        except (ValueError, TypeError):
            c_uuid = None
    stmt = select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False)  # noqa: E712
    if c_uuid is not None:
        stmt = stmt.where(Employee.company_id == c_uuid)
    emp = (await session.execute(stmt)).scalar_one_or_none()
    if not emp:
        stmt2 = select(Employee).where(Employee.id == user_id, Employee.is_deleted == False)  # noqa: E712
        if c_uuid is not None:
            stmt2 = stmt2.where(Employee.company_id == c_uuid)
        emp = (await session.execute(stmt2)).scalar_one_or_none()
    return emp.id if emp else None


def _require_payslip_settings_admin(claims: Claims) -> None:
    verified = _reject_super_admin(claims)
    role = _role(verified)
    if role not in (*ADMIN_ROLES, RoleEnum.EXECUTIVE.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only authorized Organization/HR Admins can modify company payslip branding settings.",
        )


class PayslipDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    employee_ids: list[uuid.UUID] | None = None
    employee_id: uuid.UUID | None = None
    channels: list[str] = Field(default_factory=lambda: ["email", "whatsapp"])
    is_password_protected: bool = True
    password_rule: str | None = None


class PayslipBulkGenerateRequest(BaseModel):
    run_id: uuid.UUID | None = None
    month: int | None = Field(None, ge=1, le=12)
    year: int | None = Field(None, ge=2000, le=2100)
    employee_ids: list[uuid.UUID] | None = None
    force: bool = False
    background: bool = False
    allow_draft: bool = False


class PayslipSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    company_legal_name: Optional[str] = None
    registered_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    official_email: Optional[str] = None
    official_phone: Optional[str] = None
    website: Optional[str] = None
    cin_number: Optional[str] = None
    gstin: Optional[str] = None
    pf_establishment_code: Optional[str] = None
    esic_registration_number: Optional[str] = None
    company_logo_url: Optional[str] = None
    hr_contact_name: Optional[str] = None
    hr_designation: Optional[str] = None
    hr_department: Optional[str] = None
    hr_email: Optional[str] = None
    hr_phone: Optional[str] = None
    payroll_support_email: Optional[str] = None
    office_extension: Optional[str] = None
    signatory_name: Optional[str] = None
    signatory_designation: Optional[str] = None
    signatory_department: Optional[str] = None
    signature_image_url: Optional[str] = None
    company_seal_url: Optional[str] = None
    unsigned_declaration: Optional[str] = None
    footer_declaration: Optional[str] = None
    show_zero_components: Optional[bool] = None
    show_ytd_summary: Optional[bool] = None
    show_employer_contributions: Optional[bool] = None
    enable_qr_verification: Optional[bool] = None
    show_ofc360_footer: Optional[bool] = None
    mask_pf_number: Optional[bool] = None
    allow_draft_preview: Optional[bool] = None
    default_payment_mode: Optional[str] = None


# ── Delivery & YTD ────────────────────────────────────────────────────────────

@router.post("/runs/{run_id}/deliver-payslips", status_code=status.HTTP_202_ACCEPTED, summary="Queue single or bulk payslip delivery")
async def deliver_payslips_v2(
    run_id: uuid.UUID,
    payload: PayslipDeliveryRequest | None = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)

    payload = payload or PayslipDeliveryRequest()
    employee_ids = [str(x) for x in (payload.employee_ids or ([] if payload.employee_id is None else [payload.employee_id]))]
    channels = payload.channels or ["email", "whatsapp"]
    if any(str(c).lower() not in {"email", "whatsapp"} for c in channels):
        raise HTTPException(status_code=422, detail="channels may contain only email and whatsapp")

    stmt = select(Payslip).where(Payslip.payroll_run_id == run_id, Payslip.company_id == c_uuid)
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
        run_id,
        employee_ids or None,
        channels,
        payload.password_rule,
        payload.is_password_protected,
        company_id=c_uuid,
    )
    return _ok({"job_id": job_id, "run_id": str(run_id), "status": "QUEUED", "total": len(rows)}, "Payslip delivery queued")


@router.get("/payslips/me/ytd", summary="Get the authenticated employee's April-March YTD summary")
@router.get("/me/ytd", include_in_schema=False)
async def get_my_ytd_v2(
    financial_year: str | None = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    emp_id = await _resolve_current_employee_id(db, claims, company_id=c_uuid)
    if not emp_id:
        raise HTTPException(status_code=404, detail="Employee not identified")
    result = await PayslipService.get_ytd_summary(db, emp_id, financial_year, c_uuid)
    return _ok(result, "YTD payslip summary retrieved")


@router.get("/payslips/ytd/{employee_id}", summary="Get an employee's April-March YTD summary")
async def get_employee_ytd_v2(
    employee_id: uuid.UUID,
    financial_year: str | None = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    result = await PayslipService.get_ytd_summary(db, employee_id, financial_year, c_uuid)
    return _ok(result, "YTD payslip summary retrieved")


# ── Self-Service Employee Payslip Endpoints ───────────────────────────────────

@router.get("/my-payslips", summary="Get payslips for the authenticated employee")
async def get_my_payslips_v2(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    emp_id = await _resolve_current_employee_id(db, claims, company_id=c_uuid)
    if not emp_id:
        return _ok({"items": [], "total": 0, "page": page, "limit": limit}, "No payslips available")

    res = await PayslipService.get_employee_payslips(db, employee_id=emp_id, page=page, limit=limit)
    items_data = [
        {
            "id": str(p.id),
            "run_id": str(p.payroll_run_id),
            "runId": str(p.payroll_run_id),
            "payroll_run_id": str(p.payroll_run_id),
            "employee_id": str(p.employee_id),
            "employeeId": str(p.employee_id),
            "payslip_number": p.payslip_number,
            "document_id": getattr(p, "document_id", None),
            "document_version": int(getattr(p, "document_version", 1) or 1),
            "sha256_hash": getattr(p, "sha256_hash", None),
            "period": f"{p.period_month:02d}/{p.period_year}",
            "periodName": f"{p.period_month:02d}/{p.period_year}",
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
            "net_pay_words": getattr(p, "net_pay_words", None),
            "payment_status": p.payment_status,
            "status": p.payment_status or ("GENERATED" if p.generated_at else "PENDING"),
            "document_status": getattr(p, "status", None) or ("GENERATED" if p.generated_at else "PENDING"),
            "payment_date": p.payment_date.isoformat() if p.payment_date else None,
            "released_at": p.released_at.isoformat() if getattr(p, "released_at", None) else None,
            "pdf_path": p.pdf_path,
            "download_url": f"/api/v2/payroll/my-payslips/{p.payroll_run_id}/download",
        }
        for p in res["items"]
        if getattr(p, "company_id", c_uuid) == c_uuid
    ]
    return _ok(
        {
            "items": items_data,
            "total": res["total"],
            "page": res["page"],
            "limit": res["limit"],
        },
        "My payslips retrieved successfully",
    )


@router.get("/my-payslips/{runId}/download", summary="Download payslip for authenticated employee")
async def download_my_payslip_v2(
    runId: uuid.UUID,
    inline: bool = Query(False),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    emp_id = await _resolve_current_employee_id(db, claims, company_id=c_uuid)
    if not emp_id:
        raise HTTPException(status_code=404, detail="Employee not identified.")

    content_bytes, filename = await PayslipService.get_payslip_file(
        db,
        run_id=runId,
        employee_id=emp_id,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
    )
    ps = (
        await db.execute(
            select(Payslip).where(
                Payslip.payroll_run_id == runId,
                Payslip.employee_id == emp_id,
                Payslip.company_id == c_uuid,
            )
        )
    ).scalar_one_or_none()
    if ps is not None:
        ps.download_count = (ps.download_count or 0) + 1
        await db.commit()
    return _pdf_response(content_bytes, filename, inline=inline)


@router.get("/my-provision-slips", summary="Get provision slips for authenticated employee")
async def get_my_provision_slips_v2(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    emp_id = await _resolve_current_employee_id(db, claims, company_id=c_uuid)
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


# ── Fixed-Path Enterprise Payslip Endpoints (MUST precede /{payslipId}) ───────

@router.get("/payslips/verify/{verificationToken}", summary="Verify payslip document authenticity (public minimal metadata)")
async def verify_payslip_authenticity_v2(
    verificationToken: str,
    payslip_number: Optional[str] = Query(None),
    claims: OptionalClaims = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Public / QR endpoint returning strictly non-PII verification metadata."""
    result = await PayslipService.verify_document_token(
        db,
        verificationToken,
        payslip_number=payslip_number,
    )
    return _ok(result, "Payslip verification completed")


@router.get("/payslips/settings", summary="Get company payslip branding, HR contact, signatory, and display settings")
async def get_payslip_settings_v2(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    try:
        data = await PayslipSettingsService.get_settings(db, c_uuid)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(data, "Payslip branding settings retrieved successfully")


@router.patch("/payslips/settings", summary="Update company payslip branding, HR contact, signatory, and display settings")
@router.put("/payslips/settings", include_in_schema=False)
async def update_payslip_settings_v2(
    payload: PayslipSettingsUpdateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    _require_payslip_settings_admin(claims)
    try:
        patch_data = payload.model_dump(exclude_unset=True)
        updated = await PayslipSettingsService.update_settings(
            db,
            c_uuid,
            patch_data,
            actor_id=_uid(claims),
            actor_role=_role(claims),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _ok(updated, "Payslip branding settings updated successfully")


@router.post("/payslips/settings/assets", summary="Upload company logo, authorized signature, or seal image for payslips")
async def upload_payslip_branding_asset_v2(
    asset_type: str = Query(..., description="One of: logo, signature, seal"),
    file: UploadFile = File(...),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    import os
    from app.services.company_logo_service import LOGOS_DIR, _validate_and_read

    c_uuid = _require_tenant_id(claims)
    _require_payslip_settings_admin(claims)

    kind = str(asset_type or "").strip().lower()
    field_map = {
        "logo": "company_logo_url",
        "signature": "signature_image_url",
        "seal": "company_seal_url",
    }
    if kind not in field_map:
        raise HTTPException(status_code=422, detail="asset_type must be one of: logo, signature, seal")

    data, ext = await _validate_and_read(file)
    safe_dir = os.path.join(LOGOS_DIR, str(c_uuid))
    os.makedirs(safe_dir, exist_ok=True)
    safe_filename = f"payslip_{kind}_{uuid.uuid4().hex[:10]}{ext}"
    abs_path = os.path.join(safe_dir, safe_filename)
    await asyncio.to_thread(_write_asset_file_sync, abs_path, data)
    rel_url = f"/uploads/logos/{c_uuid}/{safe_filename}"

    updated = await PayslipSettingsService.update_settings(
        db,
        c_uuid,
        {field_map[kind]: rel_url},
        actor_id=_uid(claims),
        actor_role=_role(claims),
    )
    return _ok({"asset_type": kind, "url": rel_url, "settings": updated}, "Payslip asset uploaded successfully")


def _write_asset_file_sync(path: str, content: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(content)


@router.post("/payslips/bulk-generate", summary="Bulk generate enterprise A4 payslips for a finalized payroll run")
async def bulk_generate_payslips_v2(
    payload: PayslipBulkGenerateRequest | None = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    payload = payload or PayslipBulkGenerateRequest()

    target_run: PayrollRun | None = None
    if payload.run_id is not None:
        target_run = (
            await db.execute(
                select(PayrollRun).where(PayrollRun.id == payload.run_id, PayrollRun.company_id == c_uuid)
            )
        ).scalar_one_or_none()
    elif payload.month and payload.year:
        target_run = (
            await db.execute(
                select(PayrollRun)
                .where(
                    PayrollRun.company_id == c_uuid,
                    PayrollRun.period_month == payload.month,
                    PayrollRun.period_year == payload.year,
                )
                .order_by(desc(PayrollRun.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
    else:
        raise HTTPException(status_code=422, detail="Either run_id or (month, year) must be provided.")

    if target_run is None:
        raise HTTPException(status_code=404, detail="Payroll run not found for your organization.")

    if not payload.allow_draft and str(target_run.status or "").upper() not in FINALIZED_RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Official bulk payslip generation requires an approved or finalized payroll run (current: {target_run.status}).",
        )

    emp_ids = [str(x) for x in payload.employee_ids] if payload.employee_ids else None
    if payload.background:
        job_id = await dispatch_payslip_generation(
            target_run.id,
            employee_ids=emp_ids,
            force=payload.force,
            company_id=c_uuid,
            actor_id=_uid(claims),
            actor_role=_role(claims),
            require_finalized=not payload.allow_draft,
        )
        return _ok({"job_id": job_id, "run_id": str(target_run.id), "status": "QUEUED"}, "Payslip generation queued")

    count = await PayslipService.generate_batch_payslips(
        db,
        target_run.id,
        employee_ids=emp_ids,
        force=payload.force,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
        require_finalized=not payload.allow_draft,
        release=str(target_run.status or "").upper() in FINALIZED_RUN_STATUSES,
    )
    return _ok(
        {
            "run_id": str(target_run.id),
            "generated_count": count,
            "is_draft": str(target_run.status or "").upper() not in FINALIZED_RUN_STATUSES,
        },
        f"Generated {count} enterprise payslip document(s)",
    )


@router.post("/payslips/bulk-download", summary="Bulk download payslips as a secure ZIP bundle")
async def bulk_download_payslips_v2(
    payslip_ids: list[uuid.UUID] = Body(..., embed=True),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    if not payslip_ids:
        raise HTTPException(status_code=422, detail="At least one payslip_id is required.")

    rows = list(
        (
            await db.execute(
                select(Payslip).where(Payslip.id.in_(payslip_ids), Payslip.company_id == c_uuid)
            )
        ).scalars().all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No matching payslips found for your organization.")

    ctx = await PayslipService._load_bulk_context(db, rows)
    actor_id = _uid(claims)
    actor_role = _role(claims)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ps in rows:
            pdf_bytes, filename, _, _ = await PayslipService.generate_and_store_payslip(
                db,
                payslip_id=ps.id,
                company_id=c_uuid,
                actor_id=actor_id,
                actor_role=actor_role,
                ctx=ctx,
            )
            zf.writestr(filename, pdf_bytes)
            ps.download_count = (ps.download_count or 0) + 1
    await db.commit()
    zip_buf.seek(0)
    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={
            **_PDF_SECURITY_HEADERS_BASE,
            "Content-Disposition": f'attachment; filename="payslips_bundle_{datetime.now(timezone.utc).strftime("%Y%m%d")}.zip"',
        },
    )


# ── Organization List & Item Endpoints ────────────────────────────────────────

@router.get("/payslips", summary="List organization payslips (v2)")
async def list_payslips_v2(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    runId: Optional[uuid.UUID] = Query(None),
    periodId: Optional[uuid.UUID] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    status: Optional[str] = Query(None),
    paymentStatus: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    from sqlalchemy import func, or_
    from app.api.payroll.serializers import _payslip_dict
    from app.models.payroll_models import PayrollPeriod

    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)

    stmt = (
        select(Payslip)
        .join(Employee, Payslip.employee_id == Employee.id)
        .options(selectinload(Payslip.employee))
        .where(Payslip.company_id == c_uuid)
    )
    if runId:
        stmt = stmt.where(Payslip.payroll_run_id == runId)
    if periodId:
        p_obj = (
            await db.execute(
                select(PayrollPeriod).where(PayrollPeriod.id == periodId, PayrollPeriod.company_id == c_uuid)
            )
        ).scalar_one_or_none()
        if not p_obj:
            raise HTTPException(status_code=404, detail=f"Payroll period '{periodId}' not found.")
        stmt = stmt.where(
            Payslip.period_month == p_obj.period_month,
            Payslip.period_year == p_obj.period_year,
        )
    if month:
        stmt = stmt.where(Payslip.period_month == month)
    if year:
        stmt = stmt.where(Payslip.period_year == year)
    if status and status.lower() != "all":
        if status.upper() == "GENERATED":
            stmt = stmt.where(Payslip.generated_at.isnot(None))
        elif status.upper() == "PENDING":
            stmt = stmt.where(Payslip.generated_at.is_(None))
        else:
            stmt = stmt.where(func.upper(Payslip.status) == status.upper())
    if paymentStatus and paymentStatus.lower() != "all":
        stmt = stmt.where(func.upper(Payslip.payment_status) == paymentStatus.upper())
    if department and department.lower() != "all":
        stmt = stmt.where(Employee.department == department)
    if search and search.strip():
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Employee.first_name.ilike(q),
                Employee.last_name.ilike(q),
                Employee.employee_id.ilike(q),
                Payslip.payslip_number.ilike(q),
            )
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    offset = max(0, (page - 1) * limit)
    rows = (
        await db.execute(
            stmt.order_by(desc(Payslip.period_year), desc(Payslip.period_month), desc(Payslip.created_at))
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    items_data = [_payslip_dict(p) for p in rows]
    total_pages = max(1, (total + limit - 1) // limit)
    return _ok(
        {
            "items": items_data,
            "total": total,
            "page": page,
            "limit": limit,
            "totalPages": total_pages,
        },
        "Payslips retrieved successfully",
    )


async def _load_authorized_payslip(
    db: AsyncSession,
    payslip_id: uuid.UUID,
    claims: Claims,
    *,
    action_label: str = "payslip",
    signed_token: Optional[str] = None,
) -> tuple[Payslip, uuid.UUID]:
    c_uuid = _require_tenant_id(claims)
    stmt = (
        select(Payslip)
        .where(Payslip.id == payslip_id, Payslip.company_id == c_uuid)
        .options(selectinload(Payslip.employee))
    )
    ps = (await db.execute(stmt)).scalar_one_or_none()
    if not ps:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payslip not found.")

    if signed_token is not None:
        if not PayslipService.verify_signed_download_token(
            payslip_id=ps.id,
            company_id=c_uuid,
            token=signed_token,
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired signed payslip download token.")

    if not await _is_payslip_admin_authorized(db, claims, c_uuid):
        emp_id = await _resolve_current_employee_id(db, claims, company_id=c_uuid)
        if not emp_id or emp_id != ps.employee_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: You can only view your own {action_label}.",
            )
    return ps, c_uuid


@router.get("/payslips/{payslipId}", summary="Get payslip detail by payslip ID (v2)")
async def get_payslip_by_id_v2(
    payslipId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    from app.api.payroll.serializers import _payslip_dict

    ps, c_uuid = await _load_authorized_payslip(db, payslipId, claims, action_label="payslip")
    ps.view_count = (ps.view_count or 0) + 1
    await db.commit()

    payload = _payslip_dict(ps)
    payload["run_id"] = payload.get("payroll_run_id")
    payload["snapshot"] = await PayslipService.get_payslip_preview(db, ps.id, company_id=c_uuid)
    return _ok(payload, "Payslip detail retrieved successfully")


@router.get("/payslips/{payslipId}/pdf", summary="Download or preview enterprise payslip PDF by payslip ID")
async def download_payslip_by_id_pdf_v2(
    payslipId: uuid.UUID,
    inline: bool = Query(False),
    allow_draft: bool = Query(False),
    token: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    ps, c_uuid = await _load_authorized_payslip(
        db, payslipId, claims, action_label="payslip", signed_token=token
    )
    pdf_bytes, filename, updated_ps, _ = await PayslipService.generate_and_store_payslip(
        db,
        payslip_id=ps.id,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
        require_finalized=False if allow_draft else False,
    )
    if bool(updated_ps.is_password_protected):
        emp = ps.employee or await db.get(Employee, ps.employee_id)
        if emp is not None:
            pdf_bytes, _ = await asyncio.to_thread(
                PayslipService.protect_pdf, pdf_bytes, emp, updated_ps, updated_ps.password_rule
            )
    updated_ps.download_count = (updated_ps.download_count or 0) + 1
    await db.commit()
    return _pdf_response(pdf_bytes, filename, inline=inline)


@router.post("/payslips/{payslipId}/generate", summary="Generate or revise enterprise payslip PDF document")
async def generate_single_payslip_v2(
    payslipId: uuid.UUID,
    force: bool = Query(True),
    allow_draft: bool = Query(False),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    _, filename, ps, doc = await PayslipService.generate_and_store_payslip(
        db,
        payslip_id=payslipId,
        company_id=c_uuid,
        actor_id=_uid(claims),
        actor_role=_role(claims),
        force=force,
        require_finalized=not allow_draft,
        release=True,
    )
    return _ok(
        {
            "payslip_id": str(ps.id),
            "payslip_number": ps.payslip_number,
            "document_id": doc.document_id if doc else ps.document_id,
            "version_number": doc.version_number if doc else ps.document_version,
            "status": doc.status if doc else ps.status,
            "is_draft": doc.is_draft if doc else False,
            "sha256_hash": doc.sha256_hash if doc else ps.sha256_hash,
            "verification_token": doc.verification_token if doc else ps.verification_token,
            "filename": filename,
        },
        "Enterprise payslip PDF generated successfully",
    )


@router.get("/payslips/{payslipId}/versions", summary="List immutable version history for a payslip document")
async def list_payslip_versions_v2(
    payslipId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    ps, c_uuid = await _load_authorized_payslip(db, payslipId, claims, action_label="payslip versions")
    docs = (
        await db.execute(
            select(PayslipDocument)
            .where(PayslipDocument.payslip_id == ps.id, PayslipDocument.company_id == c_uuid)
            .order_by(desc(PayslipDocument.version_number))
        )
    ).scalars().all()
    items = [
        {
            "id": str(d.id),
            "document_id": d.document_id,
            "payslip_number": d.payslip_number,
            "version_number": d.version_number,
            "status": d.status,
            "is_draft": d.is_draft,
            "is_active": d.is_active,
            "file_size_bytes": d.file_size_bytes,
            "sha256_hash": d.sha256_hash,
            "generated_at": d.generated_at.isoformat() if d.generated_at else None,
            "released_at": d.released_at.isoformat() if d.released_at else None,
        }
        for d in docs
    ]
    return _ok({"items": items, "total": len(items)}, "Payslip document versions retrieved")


@router.post("/payslips/{payslipId}/signed-url", summary="Generate short-lived signed payslip download token")
async def create_payslip_signed_url_v2(
    payslipId: uuid.UUID,
    ttl_seconds: int = Query(300, ge=30, le=3600),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    ps, c_uuid = await _load_authorized_payslip(db, payslipId, claims, action_label="payslip download link")
    token_info = PayslipService.create_signed_download_token(
        payslip_id=ps.id,
        company_id=c_uuid,
        ttl_seconds=ttl_seconds,
    )
    return _ok(
        {
            **token_info,
            "download_url": f"/api/v2/payroll/payslips/{ps.id}/pdf?token={token_info['token']}",
        },
        "Signed download URL generated",
    )


@router.post("/payslips/{payslipId}/email", summary="Email a single enterprise payslip PDF to the employee")
async def email_single_payslip_v2(
    payslipId: uuid.UUID,
    is_password_protected: bool = Query(True),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    await _require_payslip_manager_or_admin(db, claims, c_uuid)
    ps = (
        await db.execute(select(Payslip).where(Payslip.id == payslipId, Payslip.company_id == c_uuid))
    ).scalar_one_or_none()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found.")
    result = await PayslipService.deliver_payslips(
        db,
        ps.payroll_run_id,
        employee_ids=[str(ps.employee_id)],
        channels=["email"],
        is_password_protected=is_password_protected,
        company_id=c_uuid,
    )
    return _ok(result, "Payslip email delivery executed")


@router.get("/payslips/{runId}/{employeeId}", summary="Get payslip detail for an employee in a run")
async def get_payslip_detail_v2(
    runId: uuid.UUID,
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    if not await _is_payslip_admin_authorized(db, claims, c_uuid):
        caller_emp_id = await _resolve_current_employee_id(db, claims, company_id=c_uuid)
        if not caller_emp_id or caller_emp_id != employeeId:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You can only view your own payslip.",
            )
    else:
        emp = (
            await db.execute(
                select(Employee).where(Employee.id == employeeId, Employee.company_id == c_uuid)
            )
        ).scalar_one_or_none()
        if not emp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found in your organization.",
            )

    detail = await PayslipService.get_payslip_detail(db, run_id=runId, employee_id=employeeId, company_id=c_uuid)
    return _ok(detail, "Payslip detail retrieved successfully")


@router.get("/provision-slips/{provisionSlipId}/pdf", summary="Download provision slip PDF/document")
async def download_provision_slip_pdf(
    provisionSlipId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _reject_super_admin(claims)
    content_bytes, filename = await PayslipService.get_provision_slip_pdf(db, slip_id=provisionSlipId)
    return _pdf_response(content_bytes, filename)
