"""Route handlers for reimbursement claims — 100% Backend Connected."""
from __future__ import annotations

import uuid
from typing import Optional, List
from fastapi import APIRouter, Body
from pydantic import BaseModel

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.reimbursement_service import ReimbursementService
from app.schemas.auth import APIResponse

router = APIRouter()


class CopilotRequest(BaseModel):
    query: str


class CreateClaimRequest(BaseModel):
    expenseCategory: str
    claimAmount: float
    businessPurpose: str


class BulkApproveRequest(BaseModel):
    ids: List[str]


@router.get("/reimbursements", response_model=APIResponse[dict], summary="List reimbursement claims")
async def list_reimbursements(
    employee_id: Optional[uuid.UUID] = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    items = await service.list_claims(employee_id)
    return success_response({"items": items, "total": len(items)}, "Reimbursement claims retrieved.")


@router.post("/reimbursements", response_model=APIResponse[dict], summary="Create reimbursement claim")
async def create_reimbursement(
    payload: dict = Body(...),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    res = await service.create_claim(payload)
    return success_response(res, "Reimbursement claim created successfully.")


@router.post("/reimbursements/{claim_id}/approve", response_model=APIResponse[dict], summary="Approve reimbursement claim")
async def approve_reimbursement(
    claim_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    res = await service.approve_claim(claim_id)
    return success_response(res, "Reimbursement claim approved.")


@router.post("/reimbursements/{claim_id}/reject", response_model=APIResponse[dict], summary="Reject reimbursement claim")
async def reject_reimbursement(
    claim_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    res = await service.reject_claim(claim_id)
    return success_response(res, "Reimbursement claim rejected.")


@router.post("/reimbursements/bulk-approve", response_model=APIResponse[dict], summary="Bulk approve reimbursement claims")
async def bulk_approve_reimbursements(
    payload: dict = Body(...),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    ids = payload.get("ids", [])
    res = await service.bulk_approve(ids)
    return success_response(res, "Bulk approval completed.")


@router.get("/reimbursements/audit-logs", response_model=APIResponse[dict], summary="Get reimbursement audit logs")
async def get_audit_logs(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    logs = await service.get_audit_logs()
    return success_response({"items": logs}, "Audit logs retrieved.")


@router.get("/reimbursements/ai-insights", response_model=APIResponse[dict], summary="Get reimbursement AI insights")
async def get_ai_insights(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    insights = await service.get_ai_insights()
    return success_response({"items": insights}, "AI insights retrieved.")


@router.post("/reimbursements/copilot", response_model=APIResponse[dict], summary="Copilot chat assistant")
async def copilot_chat(
    payload: CopilotRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ReimbursementService(db)
    res = await service.copilot_chat(payload.query)
    return success_response(res, "Copilot reply generated.")
