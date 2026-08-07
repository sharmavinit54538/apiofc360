"""Route handlers for bonus plans, awards, and bonus listing aliases — 100% Backend Connected."""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.bonus_service import BonusService
from app.schemas.auth import APIResponse

router = APIRouter()


class CopilotRequest(BaseModel):
    query: str


@router.get("/bonus/plans", response_model=APIResponse[dict], summary="List bonus plans")
async def list_bonus_plans(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BonusService(db)
    items = await service.list_plans()
    return success_response({"items": items, "total": len(items)}, "Bonus plans retrieved.")


@router.get("/bonuses", response_model=APIResponse[dict], summary="List all bonuses")
async def list_bonuses(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BonusService(db)
    items = await service.list_plans()
    return success_response({"items": items, "total": len(items), "page": page, "page_size": page_size}, "Bonuses retrieved.")


@router.post("/bonuses", response_model=APIResponse[dict], summary="Create bonus request")
async def create_bonus(
    payload: dict = Body(...),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BonusService(db)
    res = await service.create_bonus(payload)
    return success_response(res, "Bonus request submitted.")


@router.post("/bonuses/{bonus_id}/approve", response_model=APIResponse[dict], summary="Approve bonus request")
async def approve_bonus(
    bonus_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BonusService(db)
    res = await service.approve_bonus(bonus_id)
    return success_response(res, "Bonus request approved.")


@router.post("/bonuses/{bonus_id}/reject", response_model=APIResponse[dict], summary="Reject bonus request")
async def reject_bonus(
    bonus_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BonusService(db)
    res = await service.reject_bonus(bonus_id)
    return success_response(res, "Bonus request rejected.")


@router.post("/bonuses/copilot", response_model=APIResponse[dict], summary="Copilot chat assistant")
async def copilot_chat(
    payload: CopilotRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BonusService(db)
    res = await service.copilot_chat(payload.query)
    return success_response(res, "Copilot reply generated.")
