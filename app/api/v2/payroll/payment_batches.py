"""Payment Batches router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.schemas.payroll_v2.payment_batches import (
    PaymentBatchApproveRequest,
    PaymentBatchBankFileRequest,
    PaymentBatchBankResponseApplyRequest,
    PaymentBatchItemHoldRequest,
    PaymentBatchItemReleaseRequest,
    PaymentBatchItemRetryRequest,
    PaymentBatchRejectRequest,
    PaymentBatchSubmitRequest,
)
from app.services.payroll.idempotency_service import IdempotencyService, get_optional_idempotency_key, require_idempotency_key
from app.services.payroll.payment_batch_service import PaymentBatchService
from app.workers.payroll_tasks import dispatch_bank_file_generation

router = APIRouter(tags=["Payroll v2 - Payment Batches"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _batch_dict(b) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "company_id": str(b.company_id) if b.company_id else None,
        "run_id": str(b.payroll_run_id),
        "batch_number": b.batch_number,
        "source_account_id": str(b.source_account_id),
        "payment_mode": b.payment_mode,
        "status": b.status,
        "total_amount_paise": b.total_amount_paise,
        "total_records": b.total_records,
        "bank_reference_number": b.bank_reference_number,
        "submission_date": str(b.submission_date) if b.submission_date else None,
        "notes": b.notes,
        "approved_by": str(b.approved_by) if b.approved_by else None,
        "approved_at": b.approved_at.isoformat() if b.approved_at else None,
        "remarks": b.remarks,
        "rejected_by": str(b.rejected_by) if b.rejected_by else None,
        "rejected_at": b.rejected_at.isoformat() if b.rejected_at else None,
        "rejection_reason": b.rejection_reason,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


# 1. GET /api/v2/payroll/payment-batches
@router.get("/payment-batches", summary="List payment batches")
async def list_payment_batches(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    periodId: Optional[uuid.UUID] = Query(None),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    company_id_str = claims.get("company_id") if claims else None
    c_uuid = uuid.UUID(company_id_str) if company_id_str else None
    res = await PaymentBatchService.list_batches(
        session=db,
        company_id=c_uuid,
        period_id=periodId,
        status_filter=status,
        search=search,
        page=page,
        limit=limit,
    )
    items = [_batch_dict(b) for b in res["items"]]
    return _ok({
        "items": items,
        "total": res["total"],
        "page": res["page"],
        "limit": res["limit"],
    }, "Payment batches retrieved successfully")


# 2. GET /api/v2/payroll/payment-batches/{batchId}
@router.get("/payment-batches/{batchId}", summary="Get payment batch details and items")
async def get_payment_batch(
    batchId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    res = await PaymentBatchService.get_batch_details(
        session=db,
        batch_id=batchId,
        page=page,
        limit=limit,
        status_filter=status,
        search=search,
    )
    return _ok(res, "Payment batch details retrieved successfully")


# 3. POST /api/v2/payroll/payment-batches/{batchId}/approve
@router.post("/payment-batches/{batchId}/approve", summary="Approve payment batch")
async def approve_payment_batch(
    batchId: uuid.UUID,
    payload: Optional[PaymentBatchApproveRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    remarks = payload.remarks if payload else None
    batch = await PaymentBatchService.approve_batch(
        session=db,
        batch_id=batchId,
        user_id=user_id,
        user_role=user_role,
        remarks=remarks,
    )
    return _ok(_batch_dict(batch), "Payment batch approved successfully")


# 4. POST /api/v2/payroll/payment-batches/{batchId}/bank-file
@router.post("/payment-batches/{batchId}/bank-file", summary="Generate bank payment file")
async def generate_bank_file(
    batchId: uuid.UUID,
    payload: PaymentBatchBankFileRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    dispatch_res = await dispatch_bank_file_generation(
        batch_id=str(batchId),
        format_type=payload.format,
        user_id=str(user_id) if user_id else None,
    )
    return _ok(dispatch_res, "Bank file generation task dispatched")


# 5. GET /api/v2/payroll/payment-batches/{batchId}/bank-file/download
@router.get("/payment-batches/{batchId}/bank-file/download", summary="Download generated bank payment file")
async def download_bank_file(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    content_bytes, filename, media_type = await PaymentBatchService.get_latest_bank_file(
        session=db, batch_id=batchId
    )
    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# 6. POST /api/v2/payroll/payment-batches/{batchId}/bank-response/preview
@router.post("/payment-batches/{batchId}/bank-response/preview", summary="Preview bank acknowledgement/reconciliation file")
async def preview_bank_response(
    batchId: uuid.UUID,
    file: UploadFile = File(..., description="Bank payment response file"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    preview = await PaymentBatchService.preview_bank_response(
        session=db, batch_id=batchId, file=file
    )
    return _ok(preview, "Bank response preview generated successfully")


# 7. POST /api/v2/payroll/payment-batches/{batchId}/bank-response/apply
@router.post("/payment-batches/{batchId}/bank-response/apply", summary="Apply bank response preview to update transaction states")
async def apply_bank_response(
    batchId: uuid.UUID,
    payload: PaymentBatchBankResponseApplyRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    res = await PaymentBatchService.apply_bank_response(
        session=db,
        batch_id=batchId,
        preview_token=payload.preview_token,
        allow_partial=payload.allow_partial,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok(res, "Bank response applied successfully")


# 8. POST /api/v2/payroll/payment-batches/{batchId}/items/{itemId}/hold
@router.post("/payment-batches/{batchId}/items/{itemId}/hold", summary="Hold a specific item in the payment batch")
async def hold_batch_item(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    payload: PaymentBatchItemHoldRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    item = await PaymentBatchService.hold_item(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        reason=payload.reason,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok({"id": str(item.id), "status": item.status, "hold_reason": item.hold_reason}, "Item held successfully")


# 9. POST /api/v2/payroll/payment-batches/{batchId}/items/{itemId}/release
@router.post("/payment-batches/{batchId}/items/{itemId}/release", summary="Release a held item in the payment batch")
async def release_batch_item(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    payload: Optional[PaymentBatchItemReleaseRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    remarks = payload.remarks if payload else None
    item = await PaymentBatchService.release_item(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        remarks=remarks,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok({"id": str(item.id), "status": item.status}, "Item released successfully")


# 10. POST /api/v2/payroll/payment-batches/{batchId}/items/{itemId}/retry
@router.post("/payment-batches/{batchId}/items/{itemId}/retry", summary="Retry a failed payment batch item")
async def retry_batch_item(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    payload: PaymentBatchItemRetryRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    item = await PaymentBatchService.retry_item(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        reason=payload.reason,
        updated_bank_details=payload.updated_bank_details,
        user_id=user_id,
        user_role=user_role,
    )
    return _ok({
        "id": str(item.id),
        "status": item.status,
        "retry_count": item.retry_count,
        "account_number": item.account_number,
    }, "Item reset for retry successfully")


# 11. POST /api/v2/payroll/payment-batches/{batchId}/reconcile
@router.post("/payment-batches/{batchId}/reconcile", summary="Reconcile payment batch against bank responses")
async def reconcile_payment_batch(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    batch = await PaymentBatchService.reconcile_batch(
        session=db, batch_id=batchId, user_id=user_id, user_role=user_role
    )
    return _ok(_batch_dict(batch), "Payment batch reconciled successfully")


# 12. POST /api/v2/payroll/payment-batches/{batchId}/reject
@router.post("/payment-batches/{batchId}/reject", summary="Reject payment batch")
async def reject_payment_batch(
    batchId: uuid.UUID,
    payload: PaymentBatchRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    batch = await PaymentBatchService.reject_batch(
        session=db,
        batch_id=batchId,
        user_id=user_id,
        user_role=user_role,
        reason=payload.reason,
    )
    return _ok(_batch_dict(batch), "Payment batch rejected")


# 13. POST /api/v2/payroll/payment-batches/{batchId}/submit (Idempotency-Key Required)
@router.post("/payment-batches/{batchId}/submit", summary="Submit payment batch to bank")
async def submit_payment_batch(
    batchId: uuid.UUID,
    payload: PaymentBatchSubmitRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)

    cached = await IdempotencyService.get_cached_result(idempotency_key)
    if cached:
        return cached["data"]

    await IdempotencyService.lock_key(idempotency_key)

    batch = await PaymentBatchService.submit_batch(
        session=db,
        batch_id=batchId,
        bank_reference_number=payload.bank_reference_number,
        submission_date=payload.submission_date,
        notes=payload.notes,
        user_id=user_id,
        user_role=user_role,
    )
    result = _ok(_batch_dict(batch), "Payment batch submitted successfully")
    await IdempotencyService.store_result(idempotency_key, 200, result)
    return result


# 14. POST /api/v2/payroll/payment-batches/{batchId}/validate
@router.post("/payment-batches/{batchId}/validate", summary="Validate payment batch and accounts")
async def validate_payment_batch(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    val_res = await PaymentBatchService.validate_batch(session=db, batch_id=batchId)
    return _ok(val_res, "Payment batch validation completed")
