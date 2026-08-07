"""FastAPI Route Handlers for Enterprise Payroll Compliance Management System."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.payroll_compliance import (
    PayrollComplianceSchema,
    PayrollComplianceCreateSchema,
    PayrollComplianceUpdateSchema,
    GenerateChallanSchema,
    ValidateComplianceSchema,
)
from app.services.payroll_compliance_service import PayrollComplianceService

router = APIRouter()


def _comp_to_dict(c) -> dict:
    """Helper to convert PayrollCompliance model to dictionary."""
    return {
        "id": str(c.id),
        "company_id": str(c.company_id) if c.company_id else None,
        "compliance_name": c.compliance_name,
        "compliance_code": c.compliance_code,
        "category": c.category or "EPF",
        "description": c.description or "",
        "financial_year": c.financial_year or "2026-2027",
        "state": c.state or "ALL_INDIA",
        "status": c.status or "COMPLIANT",
        "filing_frequency": c.filing_frequency or "MONTHLY",
        "due_day_of_month": c.due_day_of_month or 15,
        "is_enabled": c.is_enabled,
        "auto_file": c.auto_file,
        "auto_remind": c.auto_remind,
        "compliance_score": c.compliance_score or 100,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("/compliance/rules", response_model=APIResponse[dict], summary="List statutory compliance rules")
@router.head("/compliance/rules")
async def list_compliance_rules(
    category_filter: Optional[str] = Query(None, alias="category"),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    rules = await PayrollComplianceService.list_compliance(db, category_filter=category_filter)
    items = [_comp_to_dict(r) for r in rules]
    return success_response({"items": items, "total": len(items)}, "Statutory compliance rules retrieved successfully.")


@router.get("/compliance/audit", response_model=APIResponse[List[dict]], summary="Get compliance audit log")
async def get_compliance_audit(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayrollComplianceService.get_audit_logs(db)
    return success_response(logs, "Compliance audit log retrieved.")


@router.get("/compliance/history", response_model=APIResponse[List[dict]], summary="Get compliance version history")
async def get_compliance_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await PayrollComplianceService.get_audit_logs(db)
    return success_response(logs, "Compliance version history retrieved.")


@router.get("/compliance/calendar", response_model=APIResponse[List[dict]], summary="Get statutory due dates calendar")
async def get_compliance_calendar(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    calendar_events = [
        {"id": "cal_1", "title": "EPFO ECR Filing & Challan", "due_date": "2026-08-15", "status": "DUE_SOON", "category": "EPF"},
        {"id": "cal_2", "title": "ESIC Monthly Contribution Return", "due_date": "2026-08-15", "status": "DUE_SOON", "category": "ESI"},
        {"id": "cal_3", "title": "Professional Tax Monthly Deposit (Telangana)", "due_date": "2026-08-20", "status": "UPCOMING", "category": "PT"},
        {"id": "cal_4", "title": "Labour Welfare Fund (LWF) Semi-Annual Deposit", "due_date": "2026-12-31", "status": "UPCOMING", "category": "LWF"},
    ]
    return success_response(calendar_events, "Statutory due dates calendar retrieved.")


@router.post("/compliance/validate", response_model=APIResponse[dict], summary="Run statutory compliance audit scan")
async def validate_statutory_compliance(
    payload: ValidateComplianceSchema = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    res = await PayrollComplianceService.run_validation(db)
    return success_response(res, "Statutory compliance validation scan completed.")


@router.post("/compliance/challan", response_model=APIResponse[dict], summary="Generate EPFO ECR or ESIC Challan")
async def generate_statutory_challan(
    payload: GenerateChallanSchema,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    challan = await PayrollComplianceService.generate_challan(
        db=db,
        challan_type=payload.challan_type,
        period_month=payload.period_month,
        period_year=payload.period_year
    )
    return success_response({
        "id": str(challan.id),
        "challan_type": challan.challan_type,
        "trrn_number": challan.trrn_number,
        "total_amount": float(challan.total_amount),
        "employee_count": challan.employee_count,
        "status": challan.status,
        "file_payload": challan.file_payload,
    }, f"Statutory {challan.challan_type} generated successfully.")


@router.get("/compliance/{rule_id}", response_model=APIResponse[dict], summary="Get single compliance rule details")
async def get_compliance_rule_details(
    rule_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    item = await PayrollComplianceService.get_compliance_by_id(db, rule_id)
    if not item:
        raise HTTPException(status_code=404, detail="Compliance rule not found.")
    return success_response(_comp_to_dict(item), "Compliance rule details retrieved.")


@router.post("/compliance", status_code=201, response_model=APIResponse[dict], summary="Create new statutory compliance rule")
async def create_compliance_rule(
    payload: PayrollComplianceCreateSchema,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    try:
        created = await PayrollComplianceService.create_compliance(
            db=db,
            data=payload.model_dump(),
            actor_email=actor_email,
            ip_address=ip_address,
            browser=browser
        )
        return success_response(_comp_to_dict(created), "Statutory compliance rule created successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
