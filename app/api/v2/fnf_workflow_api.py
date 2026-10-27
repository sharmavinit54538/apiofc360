"""Clearance-guarded exit FnF finalization and settlement APIs."""
from __future__ import annotations

import os
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.departments import require_admin_or_hr
from app.db.database import get_db_session
from app.models.exit import FnfSettlement
from app.schemas.auth import APIResponse
from app.services.fnf_workflow_service import FnFWorkflowService

router = APIRouter(prefix="/exits", tags=["Exit FnF Workflow v2"])


async def _tenant_exit(service: FnFWorkflowService, exit_id: uuid.UUID, claims: dict):
    exit_obj = await service._exit(exit_id)
    if str(claims.get("role") or "").lower() != "super_admin" and str(exit_obj.company_id) != str(claims.get("company_id")):
        raise HTTPException(status_code=404, detail="Exit request not found.")
    return exit_obj


def _fnf_dict(fnf) -> dict[str, Any]:
    return {
        "id": str(fnf.id), "exit_id": str(fnf.exit_id), "status": fnf.status,
        "payment_status": fnf.payment_status, "net_payable_amount": str(fnf.net_payable_amount),
        "settlement_breakup": fnf.settlement_breakup, "statement_path": fnf.statement_path,
        "statement_hash": fnf.statement_hash, "settled_at": fnf.settled_at.isoformat() if fnf.settled_at else None,
        "generated_letters": fnf.generated_letters_json or [],
    }


@router.get("/{exit_id}/clearance", response_model=APIResponse[dict[str, Any]])
async def get_clearance(
    exit_id: uuid.UUID, claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = FnFWorkflowService(db)
    await _tenant_exit(service, exit_id, claims)
    result = await service.clearance_status(exit_id)
    return APIResponse(success=True, message="Exit clearance status retrieved.", data=result, errors=None)


@router.post("/{exit_id}/fnf/finalize", response_model=APIResponse[dict[str, Any]])
async def finalize_fnf(
    exit_id: uuid.UUID, claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = FnFWorkflowService(db)
    await _tenant_exit(service, exit_id, claims)
    try:
        fnf = await service.finalize_exit_fnf(exit_id, actor_id=uuid.UUID(claims["sub"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="FnF finalized after 100% clearance.", data=_fnf_dict(fnf), errors=None)


@router.post("/{exit_id}/fnf/settle", response_model=APIResponse[dict[str, Any]])
async def settle_fnf(
    exit_id: uuid.UUID, claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = FnFWorkflowService(db)
    await _tenant_exit(service, exit_id, claims)
    try:
        fnf = await service.settle_exit_fnf(exit_id, actor_id=uuid.UUID(claims["sub"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(success=True, message="FnF settled; settlement sheet and exit letters generated.", data=_fnf_dict(fnf), errors=None)


@router.get("/{exit_id}/fnf/settlement-sheet")
async def download_settlement_sheet(
    exit_id: uuid.UUID, claims: Annotated[dict, Depends(require_admin_or_hr)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = FnFWorkflowService(db)
    await _tenant_exit(service, exit_id, claims)
    settlement = (await db.execute(select(FnfSettlement).where(
        FnfSettlement.exit_id == exit_id
    ))).scalars().first()
    if settlement is None or not settlement.statement_path or not os.path.isfile(settlement.statement_path):
        raise HTTPException(status_code=404, detail="Settlement sheet is available after SETTLED.")
    return FileResponse(settlement.statement_path, media_type="application/pdf", filename=f"FnF_{exit_id}.pdf")


__all__ = ["router"]
