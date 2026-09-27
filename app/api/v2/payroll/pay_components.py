"""Pay Components router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.db.database import get_db_session
from app.schemas.payroll_v2.pay_components import PayComponentCreateRequest
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


# GET /api/v2/payroll/pay-components
@router.get("/pay-components", summary="List all active pay components")
async def list_pay_components(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    components = await PayComponentService.list_components(db, company_id=c_uuid)
    return _ok([_comp_dict(c) for c in components], "Pay components retrieved successfully")


# POST /api/v2/payroll/pay-components
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
