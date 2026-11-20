"""Route handlers for bank transfers, disbursements, and advice files — 100% Backend Connected."""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Query, Body, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _uid, _as_uuid
from app.api.payroll.responses import success_response
from app.api.payroll.services.bank_service import BankService
from app.models.payroll import BankAdviceFile
from app.schemas.auth import APIResponse

router = APIRouter()


class BankFileRequest(BaseModel):
    format: Optional[str] = "NEFT"


class BatchRequest(BaseModel):
    employee_count: Optional[int] = 0
    total_amount: Optional[float] = 0.0
    format: Optional[str] = "NEFT"
    pay_cycle_id: Optional[str] = None


class MarkPaidRequest(BaseModel):
    reference_number: Optional[str] = None
    remarks: Optional[str] = None


@router.get("/bank-transfers", response_model=APIResponse[dict], summary="List bank transfers")
@router.get("/bank/disbursements", response_model=APIResponse[dict], summary="List bank disbursements alias")
async def list_bank_transfers(
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    bank: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    items = await service.get_transfers(search=search, department=department, bank=bank, payment_status=payment_status)
    return success_response({"items": items, "total": len(items)}, "Bank transfers retrieved.")


@router.get("/bank-transfers/dashboard", response_model=APIResponse[dict], summary="Get bank transfer dashboard metrics")
async def get_dashboard_metrics(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    metrics = await service.get_dashboard_metrics()
    return success_response(metrics, "Bank transfer dashboard metrics retrieved.")


@router.get("/bank-transfers/audit", response_model=APIResponse[dict], summary="Get bank transfer audit logs")
async def get_audit_logs(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    logs = await service.get_audit_logs()
    return success_response({"items": logs, "total": len(logs)}, "Bank transfer audit logs retrieved.")


@router.get("/bank-transfers/download/{file_id}", summary="Download bank advice file")
async def download_bank_file(
    file_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
):
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    stmt = select(BankAdviceFile).where(BankAdviceFile.id == file_id)
    if cid:
        stmt = stmt.where(BankAdviceFile.company_id == cid)
    res = await db.execute(stmt)
    record = res.scalars().first()
    if not record or not record.file_content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank advice file not found or empty.")

    return Response(
        content=record.file_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={record.file_name}"},
    )


@router.get("/bank-transfers/{transfer_id}", response_model=APIResponse[dict], summary="Get bank transfer detail")
async def get_transfer_detail(
    transfer_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    data = await service.get_transfer_detail(transfer_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Bank transfer '{transfer_id}' not found.")
    return success_response(data, "Bank transfer detail retrieved.")


@router.post("/bank-transfers/batch", response_model=APIResponse[dict], summary="Create transfer batch")
async def create_transfer_batch(
    payload: BatchRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    res = await service.create_transfer_batch(payload.dict())
    return success_response(res, "Transfer batch created.")


@router.post("/bank-transfers/generate-file", response_model=APIResponse[dict], summary="Generate NEFT bank file")
async def generate_bank_file(
    payload: BankFileRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    res = await service.generate_bank_file(payload.format)
    return success_response(res, "Bank file generated.")


@router.post("/bank-transfers/initiate", response_model=APIResponse[dict], summary="Initiate bank transfer payments")
async def initiate_payments(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    res = await service.initiate_payments()
    return success_response(res, "Payments initiated.")


@router.post("/bank-transfers/reconcile", response_model=APIResponse[dict], summary="Reconcile bank transfer payments")
async def reconcile_payments(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    res = await service.reconcile_payments()
    return success_response(res, "Payments reconciled.")


@router.post("/bank-transfers/{transfer_id}/retry", response_model=APIResponse[dict], summary="Retry failed transfer")
async def retry_transfer(
    transfer_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    try:
        res = await service.retry_transfer(transfer_id)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return success_response(res, "Transfer retried.")


@router.post("/bank-transfers/{transfer_id}/mark-paid", response_model=APIResponse[dict], summary="Mark transfer as paid")
async def mark_as_paid(
    transfer_id: str,
    payload: Optional[MarkPaidRequest] = None,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _as_uuid(claims.get("company_id")) if claims else None
    service = BankService(db, company_id=cid, actor_id=_uid(claims))
    ref = payload.reference_number if payload else None
    remarks = payload.remarks if payload else None
    try:
        res = await service.mark_as_paid(transfer_id, transaction_ref=ref, remarks=remarks)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return success_response(res, "Transfer marked as paid.")
