"""FastAPI Route Handlers for Enterprise Allowance Management System."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.allowance import (
    AllowanceSchema,
    AllowanceCreateSchema,
    AllowanceUpdateSchema,
)
from app.services.allowance_service import AllowanceService

router = APIRouter()


def _allowance_to_dict(a) -> dict:
    """Helper to convert Allowance model to dictionary."""
    return {
        "id": str(a.id),
        "company_id": str(a.company_id) if a.company_id else None,
        "name": a.name,
        "display_name": a.display_name or a.name,
        "code": a.code,
        "description": a.description or "",
        "category": a.category or "SPECIAL",
        "earning_type": a.earning_type or "FIXED",
        "is_variable": a.is_variable,
        "frequency": a.frequency or "MONTHLY",
        "is_recurring": a.is_recurring,
        "calc_type": a.calc_type or "FIXED",
        "formula_expr": a.formula_expr or "",
        "default_amount": float(a.default_amount or 0.0),
        "min_limit": float(a.min_limit or 0.0),
        "max_limit": float(a.max_limit or 0.0),
        "currency": a.currency or "INR",
        "taxability_type": a.taxability_type or "TAXABLE",
        "exemption_limit_monthly": float(a.exemption_limit_monthly or 0.0),
        "exemption_limit_annual": float(a.exemption_limit_annual or 0.0),
        "pf_applicable": a.pf_applicable,
        "esi_applicable": a.esi_applicable,
        "pt_applicable": a.pt_applicable,
        "lwf_applicable": a.lwf_applicable,
        "included_in_ctc": a.included_in_ctc,
        "included_in_gross": a.included_in_gross,
        "included_in_net": a.included_in_net,
        "appears_on_payslip": a.appears_on_payslip,
        "is_mandatory": a.is_mandatory,
        "is_active": a.is_active,
        "display_order": a.display_order or 1,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.get("/allowances", response_model=APIResponse[dict], summary="List all allowances")
@router.head("/allowances")
async def list_allowances(
    category_filter: Optional[str] = Query(None, alias="category"),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    allowances = await AllowanceService.list_allowances(db, category_filter=category_filter)
    items = [_allowance_to_dict(a) for a in allowances]
    return success_response({"items": items, "total": len(items)}, "Allowances retrieved successfully.")


@router.get("/allowances/audit", response_model=APIResponse[List[dict]], summary="Get allowance audit log")
async def get_allowance_audit(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await AllowanceService.get_audit_logs(db)
    return success_response(logs, "Allowance audit log retrieved.")


@router.get("/allowances/history", response_model=APIResponse[List[dict]], summary="Get allowance version history")
async def get_allowance_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await AllowanceService.get_audit_logs(db)
    return success_response(logs, "Allowance version history retrieved.")


@router.get("/allowances/export", response_model=APIResponse[dict], summary="Export allowances snapshot")
async def export_allowances(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    allowances = await AllowanceService.list_allowances(db)
    items = [_allowance_to_dict(a) for a in allowances]
    return success_response({"items": items, "exported_at": datetime.utcnow().isoformat()}, "Allowances export snapshot generated.")


@router.get("/allowances/{allowance_id}", response_model=APIResponse[dict], summary="Get single allowance details")
async def get_allowance_details(
    allowance_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    item = await AllowanceService.get_allowance_by_id(db, allowance_id)
    if not item:
        raise HTTPException(status_code=404, detail="Allowance definition not found.")
    return success_response(_allowance_to_dict(item), "Allowance details retrieved.")


@router.post("/allowances", status_code=201, response_model=APIResponse[dict], summary="Create new allowance definition")
async def create_allowance(
    payload: AllowanceCreateSchema,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    try:
        created = await AllowanceService.create_allowance(
            db=db,
            data=payload.model_dump(),
            actor_email=actor_email,
            ip_address=ip_address,
            browser=browser
        )
        return success_response(_allowance_to_dict(created), "Allowance definition created successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/allowances/{allowance_id}", response_model=APIResponse[dict], summary="Update allowance definition")
@router.patch("/allowances/{allowance_id}", response_model=APIResponse[dict], summary="Partial update allowance definition")
async def update_allowance(
    allowance_id: uuid.UUID,
    payload: dict,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    updated = await AllowanceService.update_allowance(
        db=db,
        allowance_id=allowance_id,
        payload=payload,
        actor_email=actor_email,
        ip_address=ip_address,
        browser=browser
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Allowance definition not found.")
    return success_response(_allowance_to_dict(updated), "Allowance definition updated successfully.")


@router.delete("/allowances/{allowance_id}", response_model=APIResponse[dict], summary="Delete custom allowance")
async def delete_allowance(
    allowance_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    try:
        deleted = await AllowanceService.delete_allowance(db, allowance_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Allowance definition not found.")
        return success_response({"id": str(allowance_id)}, "Allowance definition deleted successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/allowances/{allowance_id}/duplicate", response_model=APIResponse[dict], summary="Duplicate allowance definition")
async def duplicate_allowance(
    allowance_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    duplicated = await AllowanceService.duplicate_allowance(db, allowance_id)
    if not duplicated:
        raise HTTPException(status_code=404, detail="Allowance definition not found.")
    return success_response(_allowance_to_dict(duplicated), "Allowance definition duplicated successfully.")


@router.post("/allowances/{allowance_id}/activate", response_model=APIResponse[dict], summary="Activate allowance")
async def activate_allowance(
    allowance_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    activated = await AllowanceService.toggle_active(db, allowance_id, active_state=True)
    if not activated:
        raise HTTPException(status_code=404, detail="Allowance definition not found.")
    return success_response(_allowance_to_dict(activated), "Allowance activated.")


@router.post("/allowances/{allowance_id}/deactivate", response_model=APIResponse[dict], summary="Deactivate allowance")
async def deactivate_allowance(
    allowance_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    deactivated = await AllowanceService.toggle_active(db, allowance_id, active_state=False)
    if not deactivated:
        raise HTTPException(status_code=404, detail="Allowance definition not found.")
    return success_response(_allowance_to_dict(deactivated), "Allowance deactivated.")
