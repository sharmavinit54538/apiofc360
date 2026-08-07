"""FastAPI Route Handlers for Enterprise Salary Components & Calculation Engine."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.salary_component import (
    SalaryComponentSchema,
    SalaryComponentCreateSchema,
    SalaryComponentUpdateSchema,
    ReorderPayloadSchema,
)
from app.services.salary_component_service import SalaryComponentService

router = APIRouter()


def _comp_to_dict(c) -> dict:
    """Helper to convert SalaryComponent model to dictionary."""
    return {
        "id": str(c.id),
        "company_id": str(c.company_id) if c.company_id else None,
        "name": c.name,
        "code": c.code,
        "component_type": c.component_type or "EARNING",
        "category": c.category or "BASIC",
        "description": c.description or "",
        "display_name": c.display_name or c.name,
        "payroll_code": c.payroll_code or c.code,
        "display_order": c.display_order or 1,
        "calc_type": c.calc_type or "FIXED",
        "formula_expr": c.formula_expr or "",
        "fixed_amount": float(c.fixed_amount or 0.0),
        "percentage_value": float(c.percentage_value or 0.0),
        "is_system": c.is_system,
        "is_mandatory": c.is_mandatory,
        "is_taxable": c.is_taxable,
        "pf_applicable": c.pf_applicable,
        "esi_applicable": c.esi_applicable,
        "pt_applicable": c.pt_applicable,
        "included_in_ctc": c.included_in_ctc,
        "included_in_gross": c.included_in_gross,
        "included_in_net": c.included_in_net,
        "appears_on_payslip": c.appears_on_payslip,
        "employee_editable": c.employee_editable,
        "hr_editable": c.hr_editable,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("/components", response_model=APIResponse[dict], summary="List all salary components")
@router.head("/components")
async def list_salary_components(
    type_filter: Optional[str] = Query(None, alias="type"),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    comps = await SalaryComponentService.list_components(db, category_filter=type_filter)
    items = [_comp_to_dict(c) for c in comps]
    return success_response({"items": items, "total": len(items)}, "Salary components retrieved successfully.")


@router.get("/components/audit", response_model=APIResponse[List[dict]], summary="Get salary components audit log")
async def get_salary_component_audit(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await SalaryComponentService.get_audit_logs(db)
    return success_response(logs, "Salary component audit log retrieved.")


@router.get("/components/history", response_model=APIResponse[List[dict]], summary="Get salary components version history")
async def get_salary_component_history(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await SalaryComponentService.get_audit_logs(db)
    return success_response(logs, "Salary component history retrieved.")


@router.get("/components/{component_id}", response_model=APIResponse[dict], summary="Get single component details")
async def get_salary_component_details(
    component_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    comp = await SalaryComponentService.get_component_by_id(db, component_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Salary component not found.")
    return success_response(_comp_to_dict(comp), "Salary component details retrieved.")


@router.post("/components", status_code=201, response_model=APIResponse[dict], summary="Create new salary component")
async def create_salary_component(
    payload: SalaryComponentCreateSchema,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    try:
        created = await SalaryComponentService.create_component(
            db=db,
            data=payload.model_dump(),
            actor_email=actor_email,
            ip_address=ip_address,
            browser=browser
        )
        return success_response(_comp_to_dict(created), "Salary component created successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/components/{component_id}", response_model=APIResponse[dict], summary="Update salary component")
@router.patch("/components/{component_id}", response_model=APIResponse[dict], summary="Partial update salary component")
async def update_salary_component(
    component_id: uuid.UUID,
    payload: dict,
    request: Request,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    ip_address = request.client.host if request.client else "127.0.0.1"
    browser = request.headers.get("user-agent", "Dashboard Web")

    updated = await SalaryComponentService.update_component(
        db=db,
        component_id=component_id,
        payload=payload,
        actor_email=actor_email,
        ip_address=ip_address,
        browser=browser
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Salary component not found.")
    return success_response(_comp_to_dict(updated), "Salary component updated successfully.")


@router.delete("/components/{component_id}", response_model=APIResponse[dict], summary="Delete salary component")
async def delete_salary_component(
    component_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    try:
        deleted = await SalaryComponentService.delete_component(db, component_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Salary component not found.")
        return success_response({"id": str(component_id)}, "Salary component deleted successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/components/{component_id}/duplicate", response_model=APIResponse[dict], summary="Duplicate salary component")
async def duplicate_salary_component(
    component_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    duplicated = await SalaryComponentService.duplicate_component(db, component_id)
    if not duplicated:
        raise HTTPException(status_code=404, detail="Salary component not found.")
    return success_response(_comp_to_dict(duplicated), "Salary component duplicated successfully.")


@router.post("/components/{component_id}/activate", response_model=APIResponse[dict], summary="Activate salary component")
async def activate_salary_component(
    component_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    activated = await SalaryComponentService.toggle_active(db, component_id, active_state=True)
    if not activated:
        raise HTTPException(status_code=404, detail="Salary component not found.")
    return success_response(_comp_to_dict(activated), "Salary component activated.")


@router.post("/components/{component_id}/deactivate", response_model=APIResponse[dict], summary="Deactivate salary component")
async def deactivate_salary_component(
    component_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    deactivated = await SalaryComponentService.toggle_active(db, component_id, active_state=False)
    if not deactivated:
        raise HTTPException(status_code=404, detail="Salary component not found.")
    return success_response(_comp_to_dict(deactivated), "Salary component deactivated.")


@router.post("/components/reorder", response_model=APIResponse[dict], summary="Reorder components display order")
async def reorder_salary_components(
    payload: ReorderPayloadSchema,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    for item in payload.items:
        comp = await SalaryComponentService.get_component_by_id(db, uuid.UUID(item.id))
        if comp:
            comp.display_order = item.display_order
            db.add(comp)
    await db.commit()
    return success_response({"success": True}, "Salary components reordered successfully.")
