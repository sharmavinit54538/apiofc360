"""Route handlers for overtime — 100% Backend Connected."""
from __future__ import annotations

import uuid
from typing import Optional, List
from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _uid, _as_uuid
from app.api.payroll.responses import success_response
from app.api.payroll.services.overtime_service import OvertimeService
from app.schemas.auth import APIResponse

router = APIRouter()


class CopilotRequest(BaseModel):
    query: str


@router.get("/overtime", response_model=APIResponse[dict], summary="List overtime entries")
async def list_overtime(
    employee_id: Optional[uuid.UUID] = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = OvertimeService(db, company_id=cid, actor_id=_uid(claims))
    items = await service.list_overtime(employee_id)
    return success_response({"items": items, "total": len(items)}, "Overtime entries retrieved.")


@router.post("/overtime", response_model=APIResponse[dict], summary="Create overtime entry")
async def create_overtime(
    payload: dict = Body(...),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = OvertimeService(db, company_id=cid, actor_id=_uid(claims))
    try:
        res = await service.create_overtime(payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    return success_response(res, "Overtime request submitted.")


@router.post("/overtime/{overtime_id}/approve", response_model=APIResponse[dict], summary="Approve overtime entry")
async def approve_overtime(
    overtime_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = OvertimeService(db, company_id=cid, actor_id=_uid(claims))
    try:
        res = await service.approve_overtime(overtime_id)
    except ValueError as e:
        sc = status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=sc, detail=str(e))
    return success_response(res, "Overtime request approved.")


@router.post("/overtime/{overtime_id}/reject", response_model=APIResponse[dict], summary="Reject overtime entry")
async def reject_overtime(
    overtime_id: str,
    payload: dict = Body(default_factory=dict),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = OvertimeService(db, company_id=cid, actor_id=_uid(claims))
    reason = payload.get("reason", "Overtime request rejected by management")
    try:
        res = await service.reject_overtime(overtime_id, reason=reason)
    except ValueError as e:
        sc = status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=sc, detail=str(e))
    return success_response(res, "Overtime request rejected.")


@router.post("/overtime/copilot", response_model=APIResponse[dict], summary="Copilot chat assistant")
async def copilot_chat(
    payload: CopilotRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = OvertimeService(db, company_id=cid, actor_id=_uid(claims))
    res = await service.copilot_chat(payload.query)
    return success_response(res, "Copilot reply generated.")
