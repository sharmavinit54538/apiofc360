"""Statutory Compliance router for Payroll v2."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Optional
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin, _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.statutory import (
    ChallanRecordRequest,
    EmployeePfUpdateRequest,
    StatutoryCaSignoffRequest,
    StatutoryConfigRequest,
    StatutoryReportRequest,
    StatutorySimulationRequest,
)
from app.services.payroll.statutory_service import StatutoryService
from app.services.compliance_monitor_service import ComplianceMonitorService
from app.workers.payroll_tasks import dispatch_statutory_report

router = APIRouter(tags=["Payroll v2 - Statutory"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _config_dict(cfg) -> dict[str, Any]:
    return {
        "id": str(cfg.id),
        "company_id": str(cfg.company_id) if cfg.company_id else None,
        "company_name": cfg.company_name,
        "pf_enabled": cfg.pf_enabled,
        "employee_pf_rate": float(cfg.employee_pf_rate) if cfg.employee_pf_rate is not None else 0.12,
        "employer_pf_rate": float(cfg.employer_pf_rate) if cfg.employer_pf_rate is not None else 0.12,
        "employer_eps_rate": float(getattr(cfg, "employer_eps_rate", 0.0833)),
        "employer_edli_rate": float(getattr(cfg, "employer_edli_rate", 0.005)),
        "pf_admin_rate": float(getattr(cfg, "pf_admin_rate", 0.005)),
        "esi_pwd_wage_ceiling": float(getattr(cfg, "esi_pwd_wage_ceiling", 25000.0)),
        "pf_wage_ceiling": float(cfg.pf_wage_ceiling) if cfg.pf_wage_ceiling is not None else 15000.0,
        "pf_on_full_basic": cfg.pf_on_full_basic,
        "esi_enabled": cfg.esi_enabled,
        "employee_esi_rate": float(cfg.employee_esi_rate) if cfg.employee_esi_rate is not None else 0.0075,
        "employer_esi_rate": float(cfg.employer_esi_rate) if cfg.employer_esi_rate is not None else 0.0325,
        "esi_wage_ceiling": float(cfg.esi_wage_ceiling) if cfg.esi_wage_ceiling is not None else 21000.0,
        "pt_state": cfg.pt_state or "MAHARASHTRA",
        "default_tax_regime": cfg.default_tax_regime or "NEW",
        "lop_basis": cfg.lop_basis or "CALENDAR_DAYS",
        "is_active": cfg.is_active,
        # Labour Codes (Code on Wages, 2019) configuration
        "labour_code_enabled": bool(getattr(cfg, "labour_code_enabled", False)),
        "min_basic_wage_ratio": float(cfg.min_basic_wage_ratio)
        if getattr(cfg, "min_basic_wage_ratio", None) is not None
        else 0.5,
        "excluded_allowance_components": list(
            getattr(cfg, "excluded_allowance_components_json", None)
            or ["HRA", "CONVEYANCE", "OVERTIME", "STATUTORY_BONUS", "COMMISSION"]
        ),
        "fixed_term_pro_rata_gratuity_enabled": bool(
            getattr(cfg, "fixed_term_pro_rata_gratuity_enabled", True)
        ),
        "source_note": getattr(cfg, "source_note", None),
        # CA / payroll-expert validation sign-off
        "payroll_maker_checker_enforced": bool(
            getattr(cfg, "payroll_maker_checker_enforced", True)
        ),
        "needs_ca_validation": {
            "pf_rates": bool(getattr(cfg, "needs_ca_validation_pf_rates", True)),
            "esi_rates": bool(getattr(cfg, "needs_ca_validation_esi_rates", True)),
            "pt_slabs": bool(getattr(cfg, "needs_ca_validation_pt_slabs", True)),
            "tds_slabs": bool(getattr(cfg, "needs_ca_validation_tds_slabs", True)),
            "gratuity": bool(getattr(cfg, "needs_ca_validation_gratuity", True)),
            "lwf": bool(getattr(cfg, "needs_ca_validation_lwf", True)),
            "labour_codes": bool(getattr(cfg, "needs_ca_validation_labour_codes", True)),
        },
        "ca_verified_by": str(cfg.ca_verified_by) if getattr(cfg, "ca_verified_by", None) else None,
        "ca_verified_at": cfg.ca_verified_at.isoformat() if getattr(cfg, "ca_verified_at", None) else None,
        "ca_certificate_ref": getattr(cfg, "ca_certificate_ref", None),
        "formula_version": getattr(cfg, "formula_version", None),
    }


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
    return _ok(_config_dict(config), "Statutory configuration retrieved successfully")


# 2. PUT /api/v2/payroll/statutory/config
@router.put("/statutory/config", summary="Update statutory compliance configuration")
@router.patch("/statutory/config", summary="Partially update statutory compliance configuration")
async def update_statutory_config(
    payload: StatutoryConfigRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    update_data = payload.model_dump(exclude_unset=True)
    cfg = await StatutoryService.update_config(db, update_data, company_id=c_uuid)
    return _ok(_config_dict(cfg), "Statutory configuration updated successfully")


# 2b. POST /api/v2/payroll/statutory/ca-signoff
@router.post(
    "/statutory/ca-signoff",
    summary="Record CA / payroll-expert validation sign-off on statutory configuration",
)
async def ca_signoff_statutory_config(
    payload: StatutoryCaSignoffRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Clear the ``needs_ca_validation_*`` flags once a CA has validated the rates.

    Restricted to admin roles (super_admin / hr_admin / it_admin) of the owning
    organization; the configuration row is always resolved from the verified JWT
    ``company_id`` claim, so a sign-off can never touch another tenant's config
    (an unknown tenant answers 404, never 403).
    """
    _require_admin(claims)
    company_id_str = claims.get("company_id") if claims else None
    if not company_id_str:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Statutory configuration not found for this organization.",
        )
    try:
        c_uuid = uuid.UUID(str(company_id_str))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Statutory configuration not found for this organization.",
        )

    result = await StatutoryService.ca_signoff(
        db,
        company_id=c_uuid,
        verified_by=_uid(claims),
        certificate_ref=payload.certificate_ref,
        formula_version=payload.formula_version,
        scopes=payload.scopes,
        remarks=payload.remarks,
        actor_role=_role(claims),
    )
    return _ok(result, "CA / payroll-expert validation sign-off recorded successfully")


# 3. POST /api/v2/payroll/statutory/simulate
@router.post("/statutory/simulate", summary="Simulate end-to-end Indian Statutory Gross-to-Net breakdown")
async def simulate_statutory(
    payload: StatutorySimulationRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    config = await StatutoryService.get_config(db, company_id=c_uuid)

    result = StatutoryService.simulate_statutory_calculation(
        basic_monthly_paise=payload.basic_monthly_paise,
        hra_monthly_paise=payload.hra_monthly_paise,
        special_allowance_monthly_paise=payload.special_allowance_monthly_paise,
        other_earnings_paise=payload.other_earnings_paise,
        paid_days=payload.paid_days,
        total_days=payload.total_days,
        state=payload.state,
        month=payload.month,
        tax_regime=payload.tax_regime,
        pf_on_full_basic=payload.pf_on_full_basic,
        declarations=payload.declarations,
        config=config,
    )
    return _ok(result, "Statutory simulation computed successfully")


# 4. POST /api/v2/payroll/statutory/reports/{component}
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


# 5. GET /api/v2/payroll/statutory/summary
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


# 6. GET /api/v2/payroll/statutory/pf-ecr
@router.get("/statutory/pf-ecr", summary="Generate official EPFO ECR v2.0 text file (#|~|# delimiter)")
async def get_pf_ecr(
    period_id: uuid.UUID = Query(..., alias="period_id", description="Payroll period UUID"),
    format: str = Query("txt", description="File format: txt (raw ECR) or json (structured)"),
    download: bool = Query(False, description="Whether to trigger immediate browser file download"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    ecr_data = await StatutoryService.generate_pf_ecr(
        session=db, period_id=period_id, company_id=c_uuid,
        delimiter="#|~|#", include_invalid=True, apply_admin_minimum=True,
    )

    if download or format.lower() == "txt":
        return Response(
            content=ecr_data["ecr_text"],
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{ecr_data["filename"]}"',
                "X-Record-Count": str(ecr_data["record_count"]),
            },
        )

    return _ok(ecr_data, "EPFO PF ECR v2.0 return generated successfully")


# 7. GET /api/v2/payroll/statutory/pf-summary
@router.get("/statutory/pf-summary", summary="Get detailed PF statutory liability breakup for a period")
async def get_pf_summary(
    period_id: uuid.UUID = Query(..., alias="period_id", description="Payroll period UUID"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    summary = await StatutoryService.get_pf_summary(
        session=db, period_id=period_id, company_id=c_uuid
    )
    return _ok(summary, "PF statutory contribution summary retrieved successfully")


# 8. GET /api/v2/payroll/statutory/filing-calendar
@router.get("/statutory/filing-calendar", summary="12-Month Statutory PF Filing Calendar tracking 15th due date")
async def get_filing_calendar(
    year: Optional[int] = Query(None, description="Calendar year (default current year)"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    calendar = await StatutoryService.get_filing_calendar(
        session=db, company_id=c_uuid, year=year
    )
    return _ok(calendar, "Monthly statutory filing calendar retrieved successfully")


# 9. POST /api/v2/payroll/statutory/challan/record
@router.post("/statutory/challan/record", summary="Record TRRN, challan date, payment date, and bank reference")
async def record_challan(
    payload: ChallanRecordRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    result = await StatutoryService.record_challan(
        session=db, company_id=c_uuid, payload=payload.model_dump()
    )
    return _ok(result, "EPFO Challan TRRN and payment recorded successfully")


# 10. POST /api/v2/payroll/statutory/challan/upload
@router.post("/statutory/challan/upload", summary="Upload Challan PDF or Payment Confirmation PDF receipt")
async def upload_challan_receipt(
    period_id: uuid.UUID = Form(..., description="Payroll Period UUID"),
    file_type: str = Form("CHALLAN", description="CHALLAN or RECEIPT"),
    file: UploadFile = File(..., description="PDF / Image document"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    result = await StatutoryService.upload_challan_file(
        session=db,
        company_id=c_uuid,
        period_id=period_id,
        file=file,
        file_type=file_type,
    )
    return _ok(result, f"Challan {file_type} uploaded and attached successfully")


# 11. GET /api/v2/payroll/statutory/uan-validation
@router.get("/statutory/uan-validation", summary="Validate 12-digit UAN format and audit active employee KYC")
async def get_uan_validation_audit(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None

    report = await StatutoryService.get_uan_validation_report(session=db, company_id=c_uuid)
    return _ok(report, "Employee UAN and PF compliance validation report generated successfully")


# 12. PATCH /api/v2/payroll/statutory/employee-pf/{employee_id}
@router.patch("/statutory/employee-pf/{employee_id}", summary="Update employee UAN, PF opt-in, international worker flag, wage ceiling toggle")
async def update_employee_pf_settings(
    employee_id: uuid.UUID,
    payload: EmployeePfUpdateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.update_employee_pf_settings(
        session=db,
        employee_id=employee_id,
        payload=payload.model_dump(exclude_unset=True),
        company_id=c_uuid,
    )
    return _ok(result, "Employee PF compliance settings updated successfully")



# 13. GET /api/v2/payroll/statutory/pf-ecr/download
@router.get("/statutory/pf-ecr/download", summary="Download EPFO ECR v2 using the #~# delimiter")
async def download_pf_ecr(
    period_id: uuid.UUID = Query(..., description="Payroll period UUID"),
    strict: bool = Query(False, description="Reject the download when member validation fails"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.generate_pf_ecr(
        session=db, period_id=period_id, company_id=c_uuid,
        delimiter="#~#", include_invalid=False, apply_admin_minimum=False, strict=strict,
    )
    return Response(
        content=result["ecr_text"], media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
            "X-Record-Count": str(result["record_count"]),
            "X-Validation-Errors": str(len(result["validation_errors"])),
        },
    )


@router.get("/statutory/esi-return", summary="Generate the monthly ESIC contribution return")
@router.get("/statutory/esi-return/download", include_in_schema=False)
async def get_esi_return(
    period_id: uuid.UUID = Query(...),
    format: str = Query("csv", description="csv/txt download or json metadata"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.generate_esi_return(db, period_id, c_uuid, format.lower())
    if format.lower() == "json":
        result.pop("content", None)
        result.pop("csv_text", None)
        return _ok(result, "ESI return generated successfully")
    return Response(
        content=result["content"], media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"', "X-Record-Count": str(result["record_count"])},
    )


@router.get("/statutory/esi-challan", summary="Generate and persist the monthly ESIC challan")
async def generate_esi_challan(
    period_id: uuid.UUID = Query(...),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.generate_esi_challan(db, period_id, c_uuid)
    result.pop("content", None)
    result.pop("csv_text", None)
    return _ok(result, "ESI challan generated successfully")


@router.get("/statutory/esi-challan/download", summary="Download the monthly ESIC challan return")
async def download_esi_challan(
    period_id: uuid.UUID = Query(...),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.generate_esi_challan(db, period_id, c_uuid)
    return Response(
        content=result["csv_text"], media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ESIC_Challan_{result["period_year"]}_{result["period_month"]:02d}.csv"', "X-Challan-Id": result["challan_id"]},
    )


@router.get("/statutory/lwf-summary", summary="Get state-wise employee and employer LWF liabilities")
async def get_lwf_summary(
    period_id: uuid.UUID = Query(...),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.get_lwf_summary(db, period_id, c_uuid)
    return _ok(result, "LWF summary generated successfully")


def _form_payload_ids(payload: dict[str, Any]) -> tuple[uuid.UUID, Optional[str], Optional[int], dict[str, Any]]:
    raw_period = payload.get("period_id") or payload.get("periodId")
    if not raw_period:
        raise HTTPException(status_code=422, detail="period_id is required")
    try:
        period_id = uuid.UUID(str(raw_period))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid period_id")
    details = payload.get("challan_details") or payload.get("challanDetails") or payload.get("challan") or {}
    return period_id, payload.get("financial_year") or payload.get("financialYear"), payload.get("quarter"), details


@router.post("/statutory/form-138/draft", summary="Generate a validated quarterly Form 138 draft")
async def create_form138_draft(
    payload: dict[str, Any] = Body(default={}),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    period_id, fy, quarter, details = _form_payload_ids(payload)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.generate_form138_draft(
        db, period_id=period_id, company_id=c_uuid, quarter=quarter,
        financial_year=fy, challan_details=details, generated_by=_uid(claims),
    )
    return _ok(result, "Form 138 draft generated successfully")


@router.get("/statutory/form-138/download", summary="Download a quarterly Form 138 CSV draft")
async def download_form138(
    period_id: uuid.UUID = Query(...),
    quarter: Optional[int] = Query(None),
    financial_year: Optional[str] = Query(None),
    bsr_code: Optional[str] = Query(None),
    challan_serial_number: Optional[str] = Query(None),
    challan_date: Optional[date] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
    format: str = Query("csv", description="csv or pdf"),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    details = {"bsr_code": bsr_code, "challan_serial_number": challan_serial_number, "challan_date": challan_date}
    result = await StatutoryService.generate_form138_draft(
        db, period_id=period_id, company_id=c_uuid, quarter=quarter,
        financial_year=financial_year, challan_details=details, generated_by=_uid(claims),
    )
    if format.lower() == "json":
        result.pop("content", None)
        result.pop("csv_text", None)
        return _ok(result, "Form 138 draft generated successfully")
    if format.lower() == "pdf":
        challan_rows = [["BSR", "Serial", "Date"], [str(result["challan"].get("bsr_code") or ""), str(result["challan"].get("challan_serial_number") or ""), str(result["challan"].get("challan_date") or "")]]
        employee_rows = [["PAN", "Employee", "Month", "Gross", "TDS"]] + [[row["pan"], row["employee_name"], f"{row['period_month']:02d}/{row['period_year']}", row["gross_salary"], row["tds"]] for row in result["rows"]]
        pdf = StatutoryService._pdf_document(f"Form 138 - {result['financial_year']} Q{result['quarter']}", [("Challan Details", challan_rows), ("Employee Rows", employee_rows)])
        return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="Form138_{result["financial_year"]}_Q{result["quarter"]}.pdf"', "X-Form-Valid": str(result["is_valid"]).lower()})
    return Response(
        content=result["content"], media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"', "X-Form-Valid": str(result["is_valid"]).lower()},
    )


@router.get("/statutory/form-130/download", summary="Download annual Form 130 PDF")
async def download_form130(
    employee_id: uuid.UUID = Query(...),
    financial_year: Optional[str] = Query(None),
    period_id: Optional[uuid.UUID] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    today = date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    fy = financial_year or f"{start_year}-{start_year + 1}"
    result = await StatutoryService.generate_form130(
        db, employee_id=employee_id, financial_year=financial_year or fy, company_id=c_uuid,
        generated_by=_uid(claims), period_id=period_id,
    )
    return Response(
        content=result["pdf_bytes"], media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"', "X-Form-Id": result["form_id"]},
    )


@router.post("/statutory/form-130/generate", summary="Generate annual Form 130 PDF")
async def generate_form130(
    payload: dict[str, Any] = Body(default={}),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    raw_employee = payload.get("employee_id") or payload.get("employeeId")
    if not raw_employee:
        raise HTTPException(status_code=422, detail="employee_id is required")
    try:
        employee_id = uuid.UUID(str(raw_employee))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid employee_id")
    today = date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    fy = payload.get("financial_year") or payload.get("financialYear") or f"{start_year}-{start_year + 1}"
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    result = await StatutoryService.generate_form130(
        db, employee_id=employee_id, financial_year=fy, company_id=c_uuid,
        generated_by=_uid(claims), declarations=payload.get("declarations"),
        period_id=uuid.UUID(str(payload["period_id"])) if payload.get("period_id") else (uuid.UUID(str(payload["periodId"])) if payload.get("periodId") else None),
    )
    # Metadata endpoint; use the download route for the binary document.
    result.pop("pdf_bytes", None)
    result.pop("content", None)
    return _ok(result, "Form 130 PDF generated successfully")


# Non-hyphenated aliases used by a few statutory filing integrations.
@router.post("/statutory/form138/draft", include_in_schema=False)
async def create_form138_draft_alias(payload: dict[str, Any] = Body(default={}), claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    return await create_form138_draft(payload, claims, db)


@router.get("/statutory/form138/download", include_in_schema=False)
async def download_form138_alias(period_id: uuid.UUID = Query(...), quarter: Optional[int] = Query(None), financial_year: Optional[str] = Query(None), claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    return await download_form138(period_id, quarter, financial_year, None, None, None, claims, db)


@router.get("/statutory/form130/download", include_in_schema=False)
async def download_form130_alias(employee_id: uuid.UUID = Query(...), financial_year: Optional[str] = Query(None), period_id: Optional[uuid.UUID] = Query(None), claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    return await download_form130(employee_id=employee_id, financial_year=financial_year, period_id=period_id, claims=claims, db=db)


@router.post("/statutory/tds/calculate", summary="Calculate FY old/new-regime TDS in integer paise")
async def calculate_statutory_tds(
    payload: dict[str, Any] = Body(default={}),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    fy = payload.get("financial_year") or payload.get("financialYear") or "2024-2025"
    regime = payload.get("tax_regime") or payload.get("taxRegime") or "NEW"
    gross_paise = payload.get("annual_gross_paise") or payload.get("annualGrossPaise")
    if gross_paise is None:
        gross_paise = StatutoryService._amount_paise(payload.get("annual_gross", payload.get("annualGross", 0)))
    rule = payload.get("tax_rules") or payload.get("taxRules")
    if rule is None:
        rule = await StatutoryService.get_financial_year_tax_rule(db, fy, regime, c_uuid)
    result = StatutoryService.calculate_tds(
        annual_gross_paise=int(gross_paise), tax_regime=regime,
        declarations=payload.get("declarations"), verified_declarations=payload.get("verified_declarations") or payload.get("verifiedDeclarations"),
        proof_cutoff_passed=bool(payload.get("proof_cutoff_passed", payload.get("proofCutoffPassed", False))),
        use_verified_declarations=payload.get("use_verified_declarations", payload.get("useVerifiedDeclarations")),
        remaining_months=int(payload.get("remaining_months", payload.get("remainingMonths", 12))),
        current_month=payload.get("current_month", payload.get("currentMonth")),
        financial_year=fy, tax_rules=rule,
        ytd_tds_paise=int(payload.get("ytd_tds_paise", payload.get("ytdTdsPaise", 0)) or 0),
        previous_employer_tds_paise=int(payload.get("previous_employer_tds_paise", payload.get("previousEmployerTdsPaise", 0)) or 0),
        previous_employer_income_paise=int(payload.get("previous_employer_income_paise", payload.get("previousEmployerIncomePaise", 0)) or 0),
        one_time_bonus_paise=int(payload.get("one_time_bonus_paise", payload.get("oneTimeBonusPaise", 0)) or 0),
        variable_pay_paise=int(payload.get("variable_pay_paise", payload.get("variablePayPaise", 0)) or 0),
        basic_annual_paise=int(payload.get("basic_annual_paise", payload.get("basicAnnualPaise", 0)) or 0),
        hra_annual_paise=int(payload.get("hra_annual_paise", payload.get("hraAnnualPaise", 0)) or 0),
        rent_paid_annual_paise=int(payload.get("rent_paid_annual_paise", payload.get("rentPaidAnnualPaise", 0)) or 0),
        metro=bool(payload.get("metro", False)),
        slabs=payload.get("slabs"), standard_deduction_paise=payload.get("standard_deduction_paise"),
        standard_deduction=payload.get("standard_deduction"),
        rebate_87a_limit_paise=payload.get("rebate_87a_limit_paise"),
        rebate_87a_max_paise=payload.get("rebate_87a_max_paise"),
        cess_rate=payload.get("cess_rate"), chapter_via_limits=payload.get("chapter_via_limits"),
        chapter_via_limits_paise=payload.get("chapter_via_limits_paise"),
        surcharge_slabs=payload.get("surcharge_slabs"),
    )
    return _ok(result, "TDS calculated successfully")


@router.get("/statutory/tax-rules/{financial_year}/{regime}", summary="Get configurable FY tax slabs")
async def get_fy_tax_rule(financial_year: str, regime: str, claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    rule = await StatutoryService.get_financial_year_tax_rule(db, financial_year, regime, c_uuid)
    if rule is None:
        data = StatutoryService._default_tax_rule(financial_year, "OLD" if regime.upper().startswith("OLD") else "NEW")
        data = StatutoryService._json_safe(data)
        data.update({"financial_year": financial_year, "regime": regime.upper(), "is_default": True})
    else:
        data = {column: getattr(rule, column) for column in ("financial_year", "regime", "slabs_json", "standard_deduction_paise", "rebate_87a_limit_paise", "rebate_87a_max_paise", "chapter_via_limits_json", "surcharge_slabs_json", "cess_rate", "proof_cutoff_date", "needs_ca_validation")}
        data["is_default"] = False
    return _ok(data, "FY tax rule retrieved successfully")


@router.put("/statutory/tax-rules/{financial_year}/{regime}", summary="Configure FY tax slabs and deduction limits")
async def put_fy_tax_rule(financial_year: str, regime: str, payload: dict[str, Any] = Body(default={}), claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    rule = await StatutoryService.upsert_financial_year_tax_rule(db, financial_year, regime, payload, c_uuid)
    return _ok({"id": str(rule.id), "financial_year": rule.financial_year, "regime": rule.regime, "slabs_json": rule.slabs_json, "standard_deduction_paise": rule.standard_deduction_paise, "needs_ca_validation": rule.needs_ca_validation}, "FY tax rule saved successfully")


@router.get("/statutory/state-rules/{state}", summary="Get effective state PT/LWF rules")
async def get_state_rule(state: str, as_of: Optional[date] = Query(None), claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    rule = await StatutoryService.get_state_statutory_rule(db, state, c_uuid, as_of)
    source = rule or StatutoryService._default_rule(StatutoryService._state_code(state))
    data = {
        "state_code": StatutoryService._state_code(state),
        "state_name": StatutoryService._rule_value(source, "state_name", default=StatutoryService._state_code(state)),
        "effective_from": StatutoryService._rule_value(source, "effective_from", default=None),
        "effective_to": StatutoryService._rule_value(source, "effective_to", default=None),
        "pt_slabs_json": StatutoryService._rule_value(source, "pt_slabs_json", "pt_slabs", default=[]),
        "lwf_employee_paise": StatutoryService._rule_value(source, "lwf_employee_paise", default=0),
        "lwf_employer_paise": StatutoryService._rule_value(source, "lwf_employer_paise", default=0),
        "lwf_frequency": StatutoryService._rule_value(source, "lwf_frequency", default="MONTHLY"),
        "lwf_applicable_months": StatutoryService._rule_value(source, "lwf_applicable_months", default=[]),
        "needs_ca_validation": StatutoryService._rule_value(source, "needs_ca_validation", default=True),
        "is_default": rule is None,
    }
    return _ok(data, "State statutory rule retrieved successfully")


@router.put("/statutory/state-rules/{state}", summary="Configure versioned state PT/LWF rules")
async def put_state_rule(state: str, payload: dict[str, Any] = Body(default={}), claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    rule = await StatutoryService.upsert_state_statutory_rule(db, state, payload, c_uuid)
    return _ok({"id": str(rule.id), "state_code": rule.state_code, "effective_from": rule.effective_from, "pt_slabs_json": rule.pt_slabs_json, "lwf_employee_paise": rule.lwf_employee_paise, "lwf_employer_paise": rule.lwf_employer_paise, "needs_ca_validation": rule.needs_ca_validation}, "State statutory rule saved successfully")


@router.post("/statutory/state-rules/seed", summary="Idempotently seed default state PT/LWF rules")
async def seed_state_rules(claims: Claims = None, db: AsyncSession = Depends(get_db_session)):
    _require_admin(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    created = await StatutoryService.seed_state_statutory_rules(db, c_uuid)
    return _ok({"created": created, "states": list(StatutoryService.DEFAULT_STATE_RULES)}, "State statutory rules seeded successfully")


class StatutoryFilingTrackRequest(BaseModel):
    payment_date: date
    filing_reference: Optional[str] = None
    challan_number: Optional[str] = None
    utr_number: Optional[str] = None
    remarks: Optional[str] = Field(None, max_length=500)


def _required_company(claims: dict) -> uuid.UUID:
    value = claims.get("company_id") if claims else None
    if not value:
        raise HTTPException(status_code=403, detail="Tenant claim is required")
    return uuid.UUID(str(value))


@router.get("/statutory/compliance-calendar", summary="Unified monthly/quarterly/annual statutory compliance calendar")
async def get_compliance_calendar(
    year: int = Query(..., ge=2000, le=2200), frequency: Optional[str] = Query(None),
    claims: Claims = None, db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    try:
        rows = await ComplianceMonitorService(db).get_statutory_calendar(
            company_id=_required_company(claims), year=year, frequency=frequency,
        )
        return _ok(rows, "Statutory compliance calendar retrieved")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/statutory/filings/{due_date_id}/track", summary="Track a statutory filing and payment against its due date")
async def track_statutory_filing(
    due_date_id: uuid.UUID, payload: StatutoryFilingTrackRequest,
    claims: Claims = None, db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    try:
        row = await ComplianceMonitorService(db).track_statutory_filing(
            due_date_id, company_id=_required_company(claims), **payload.model_dump(),
        )
        return _ok({"id": str(row.id), "status": row.status, "payment_date": row.payment_date.isoformat(),
                    "filing_reference": row.filing_reference, "utr_number": row.utr_number}, "Statutory filing tracked")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/statutory/challans/archive", summary="Search the statutory challan and payment-receipt archive")
async def get_statutory_challan_archive(
    year: Optional[int] = Query(None), month: Optional[int] = Query(None, ge=1, le=12),
    challan_type: Optional[str] = Query(None), claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    rows = await ComplianceMonitorService(db).get_challan_archive(
        company_id=_required_company(claims), year=year, month=month, challan_type=challan_type,
    )
    return _ok(rows, "Statutory challan archive retrieved")


@router.get("/statutory/registers/{register_type}", summary="Generate Form B, Form D, Fines/Deductions, or Bonus register")
async def generate_statutory_register_api(
    register_type: str, year: int = Query(..., ge=2000, le=2200),
    month: int = Query(..., ge=1, le=12), legal_entity_id: Optional[uuid.UUID] = Query(None),
    output_format: str = Query("json", alias="format"), claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    try:
        result = await ComplianceMonitorService(db).generate_statutory_register(
            register_type, company_id=_required_company(claims), year=year, month=month,
            legal_entity_id=legal_entity_id,
        )
        if output_format.lower() == "csv":
            return Response(content=result["csv_content"], media_type="text/csv", headers={
                "Content-Disposition": f'attachment; filename="{result["file_name"]}"'
            })
        if output_format.lower() != "json":
            raise HTTPException(status_code=400, detail="format must be json or csv")
        result.pop("csv_content", None)
        return _ok(result, "Statutory register generated from live records")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
