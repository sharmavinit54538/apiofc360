"""Statutory Compliance router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.payroll_v2.statutory import (
    ChallanRecordRequest,
    EmployeePfUpdateRequest,
    StatutoryConfigRequest,
    StatutoryReportRequest,
    StatutorySimulationRequest,
)
from app.services.payroll.statutory_service import StatutoryService
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
        session=db, period_id=period_id, company_id=c_uuid
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
    result = await StatutoryService.update_employee_pf_settings(
        session=db,
        employee_id=employee_id,
        payload=payload.model_dump(exclude_unset=True),
    )
    return _ok(result, "Employee PF compliance settings updated successfully")

