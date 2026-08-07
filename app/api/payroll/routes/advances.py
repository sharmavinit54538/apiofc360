"""Route handlers for advances and loans — 100% Backend Connected."""
from __future__ import annotations

import uuid
from typing import Optional, List
from fastapi import APIRouter, Body
from pydantic import BaseModel

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.advance_service import AdvanceService
from app.schemas.auth import APIResponse

router = APIRouter()


class CopilotRequest(BaseModel):
    query: str


@router.get("/advances", response_model=APIResponse[dict], summary="List advances/loans")
@router.get("/loans", response_model=APIResponse[dict], summary="List advances/loans alias")
async def list_loans(
    employee_id: Optional[uuid.UUID] = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = AdvanceService(db)
    items = await service.list_loans(employee_id)
    return success_response({"items": items, "total": len(items)}, "Advances retrieved.")


@router.post("/advances", response_model=APIResponse[dict], summary="Create advance request")
async def create_loan(
    payload: dict = Body(...),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = AdvanceService(db)
    res = await service.create_loan(payload)
    return success_response(res, "Advance request submitted.")


@router.post("/advances/{loan_id}/approve", response_model=APIResponse[dict], summary="Approve advance request")
async def approve_loan(
    loan_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = AdvanceService(db)
    res = await service.approve_loan(loan_id)
    return success_response(res, "Advance request approved.")


@router.post("/advances/{loan_id}/reject", response_model=APIResponse[dict], summary="Reject advance request")
async def reject_loan(
    loan_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = AdvanceService(db)
    res = await service.reject_loan(loan_id)
    return success_response(res, "Advance request rejected.")


@router.post("/advances/copilot", response_model=APIResponse[dict], summary="Copilot chat assistant")
async def copilot_chat(
    payload: CopilotRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = AdvanceService(db)
    res = await service.copilot_chat(payload.query)
    return success_response(res, "Copilot reply generated.")
