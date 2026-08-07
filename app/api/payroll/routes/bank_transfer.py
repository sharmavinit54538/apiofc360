"""Route handlers for bank transfers, disbursements, and advice files — 100% Backend Connected."""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.bank_service import BankService
from app.schemas.auth import APIResponse

router = APIRouter()


class BankFileRequest(BaseModel):
    format: Optional[str] = "NEFT"


class BatchRequest(BaseModel):
    employee_count: Optional[int] = 0
    total_amount: Optional[float] = 0.0


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
    service = BankService(db)
    items = await service.get_transfers(search=search, department=department, bank=bank, payment_status=payment_status)
    return success_response({"items": items, "total": len(items)}, "Bank transfers retrieved.")


@router.get("/bank-transfers/dashboard", response_model=APIResponse[dict], summary="Get bank transfer dashboard metrics")
async def get_dashboard_metrics(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    metrics = await service.get_dashboard_metrics()
    return success_response(metrics, "Bank transfer dashboard metrics retrieved.")


@router.get("/bank-transfers/audit", response_model=APIResponse[dict], summary="Get bank transfer audit logs")
async def get_audit_logs(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    logs = await service.get_audit_logs()
    return success_response({"items": logs, "total": len(logs)}, "Bank transfer audit logs retrieved.")


@router.get("/bank-transfers/{transfer_id}", response_model=APIResponse[dict], summary="Get bank transfer detail")
async def get_transfer_detail(
    transfer_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    data = await service.get_transfer_detail(transfer_id)
    return success_response(data, "Bank transfer detail retrieved.")


@router.post("/bank-transfers/batch", response_model=APIResponse[dict], summary="Create transfer batch")
async def create_transfer_batch(
    payload: BatchRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    res = await service.create_transfer_batch(payload.dict())
    return success_response(res, "Transfer batch created.")


@router.post("/bank-transfers/generate-file", response_model=APIResponse[dict], summary="Generate NEFT bank file")
async def generate_bank_file(
    payload: BankFileRequest,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    res = await service.generate_bank_file(payload.format)
    return success_response(res, "Bank file generated.")


@router.post("/bank-transfers/initiate", response_model=APIResponse[dict], summary="Initiate bank transfer payments")
async def initiate_payments(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    res = await service.initiate_payments()
    return success_response(res, "Payments initiated.")


@router.post("/bank-transfers/reconcile", response_model=APIResponse[dict], summary="Reconcile bank transfer payments")
async def reconcile_payments(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    res = await service.reconcile_payments()
    return success_response(res, "Payments reconciled.")


@router.post("/bank-transfers/{transfer_id}/retry", response_model=APIResponse[dict], summary="Retry failed transfer")
async def retry_transfer(
    transfer_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    res = await service.retry_transfer(transfer_id)
    return success_response(res, "Transfer retried.")


@router.post("/bank-transfers/{transfer_id}/mark-paid", response_model=APIResponse[dict], summary="Mark transfer as paid")
async def mark_as_paid(
    transfer_id: str,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = BankService(db)
    res = await service.mark_as_paid(transfer_id)
    return success_response(res, "Transfer marked as paid.")
