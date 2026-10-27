"""Pay Components router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.payroll_v2.pay_components import PayComponentCreateRequest
from app.services.payroll.formula_evaluator import SafeFormulaEvaluator
from app.services.payroll.pay_component_service import PayComponentService

router = APIRouter(tags=["Payroll v2 - Pay Components"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _comp_dict(c) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "company_id": str(c.company_id) if c.company_id else None,
        "code": c.code,
        "name": c.name,
        "type": c.type,
        "taxable": c.taxable,
        "statutory": c.statutory,
        "calculation_method": c.calculation_method,
        "default_percentage": float(c.default_percentage) if c.default_percentage is not None else None,
        "formula_expr": c.formula_expr,
        "description": c.description,
        "effective_date": str(c.effective_date),
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


class EvaluateFormulaRequest(BaseModel):
    formula: str = Field(..., description="Mathematical formula e.g. 'basic * 0.40'")
    sample_context: Optional[dict[str, float]] = Field(
        default=None,
        description="Variables to test with e.g. {'basic': 50000, 'ctc': 1200000}",
    )


class PayComponentUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    taxable: Optional[bool] = None
    statutory: Optional[bool] = None
    calculation_method: Optional[str] = None
    default_percentage: Optional[float] = None
    formula_expr: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# 1. GET /api/v2/payroll/pay-components
@router.get("/pay-components", summary="List all active pay components")
async def list_pay_components(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    components = await PayComponentService.list_components(db, company_id=c_uuid)
    return _ok([_comp_dict(c) for c in components], "Pay components retrieved successfully")


# 2. POST /api/v2/payroll/pay-components
@router.post("/pay-components", status_code=status.HTTP_201_CREATED, summary="Create a new pay component")
async def create_pay_component(
    payload: PayComponentCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    component = await PayComponentService.create_component(db, payload=payload, company_id=c_uuid)
    return _ok(_comp_dict(component), f"Pay component '{component.code}' created successfully")


# 3. PUT /api/v2/payroll/pay-components/{id}
@router.put("/pay-components/{id}", summary="Update an existing pay component")
async def update_pay_component(
    id: uuid.UUID,
    payload: PayComponentUpdateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    update_data = payload.model_dump(exclude_unset=True)
    component = await PayComponentService.update_component(db, component_id=id, payload=update_data)
    return _ok(_comp_dict(component), f"Pay component '{component.code}' updated successfully")


# 4. DELETE /api/v2/payroll/pay-components/{id}
@router.delete("/pay-components/{id}", summary="Deactivate a pay component")
async def delete_pay_component(
    id: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PayComponentService.delete_component(db, component_id=id)
    return _ok(res, "Pay component deactivated successfully")


# 5. POST /api/v2/payroll/pay-components/evaluate-formula
@router.post("/pay-components/evaluate-formula", summary="Safely validate and evaluate a formula expression")
async def evaluate_formula(payload: EvaluateFormulaRequest):
    ctx = {
        "basic": 50000.0,
        "ctc": 1200000.0,
        "gross": 80000.0,
        "hra": 20000.0,
        "special": 10000.0,
        "paid_days": 30.0,
        "lop_days": 0.0,
        "total_days": 30.0,
    }
    if payload.sample_context:
        ctx.update(payload.sample_context)

    is_valid, msg = SafeFormulaEvaluator.validate_formula(payload.formula)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    try:
        val = SafeFormulaEvaluator.evaluate(payload.formula, ctx)
        return _ok({"formula": payload.formula, "computed_value": val, "context": ctx}, "Formula evaluated successfully")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# 6. POST /api/v2/payroll/pay-components/seed-defaults
@router.post("/pay-components/seed-defaults", summary="Seed standard Indian salary components")
async def seed_defaults(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    components = await PayComponentService.seed_default_indian_components(db, company_id=c_uuid)
    return _ok([_comp_dict(c) for c in components], "Standard Indian salary components initialized successfully")
