"""Payment Batches router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import (
    _reject_super_admin,
    _require_admin_or_manager,
    _require_tenant_id,
    _role,
    _uid,
)
from app.db.database import get_db_session
from app.schemas.payroll_v2.payment_batches import (
    PaymentBatchApproveRequest,
    PaymentBatchBankFileRequest,
    PaymentBatchBankResponseApplyRequest,
    PaymentBatchCancelRequest,
    PaymentBatchCreateRequest,
    PaymentBatchItemHoldRequest,
    PaymentBatchItemReleaseRequest,
    PaymentBatchItemRetryRequest,
    PaymentBatchReconcileRequest,
    PaymentBatchRecordResultsRequest,
    PaymentBatchRejectRequest,
    PaymentBatchRetryFailedRequest,
    PaymentBatchSubmitForApprovalRequest,
    PaymentBatchSubmitRequest,
    PaymentBatchUpdateRequest,
)
from app.schemas.payroll_v2.runs import HeldEmployeeItem
from app.services.payroll.idempotency_service import require_idempotency_key
from app.services.payroll.payment_batch_service import PaymentBatchService


async def _payment_batch_scope(
    request: Request,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Enforce company-scoped payroll roles and reject platform Super Admin."""
    _require_admin_or_manager(claims)
    _reject_super_admin(claims)
    tenant_uuid = _require_tenant_id(claims)
    batch_id = request.path_params.get("batchId")
    if batch_id:
        try:
            batch_uuid = uuid.UUID(str(batch_id))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid payment batch ID.") from exc
        await PaymentBatchService.get_batch(db, batch_uuid, company_id=tenant_uuid)


router = APIRouter(tags=["Payroll v2 - Payment Batches"], dependencies=[Depends(_payment_batch_scope)])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


async def _serialize_batch(db: AsyncSession, batch: Any) -> dict[str, Any]:
    ctx = await PaymentBatchService.build_batch_contexts(db, [batch])
    return PaymentBatchService.serialize_batch(batch, ctx)


# ---------------------------------------------------------------------------
# Static collection/summary routes (must stay registered BEFORE /{batchId})
# ---------------------------------------------------------------------------


@router.get("/payment-batches/summary", summary="Get payroll payment dashboard summary")
@router.get("/payment-batches/dashboard", summary="Get payroll payment dashboard summary (alias)")
async def get_payment_dashboard_summary(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    summary = await PaymentBatchService.get_dashboard_summary(db, c_uuid)
    return _ok(summary, "Payment dashboard summary retrieved successfully")


@router.get("/payment-batches/eligible-runs", summary="List locked payroll runs eligible for a payment batch")
async def get_eligible_payroll_runs(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    runs = await PaymentBatchService.get_eligible_runs(db, c_uuid)
    return _ok(runs, "Eligible payroll runs retrieved successfully")


@router.get("/payment-modes", summary="Get supported company bank payment modes")
async def get_supported_payment_modes(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    modes = await PaymentBatchService.get_supported_payment_modes(db, c_uuid)
    return _ok(modes, "Supported payment modes retrieved successfully")


@router.post("/payment-batches", status_code=status.HTTP_201_CREATED, summary="Create payment batch from payroll run")
async def create_payment_batch(
    payload: PaymentBatchCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    try:
        run_uuid = uuid.UUID(str(payload.run_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid payroll run ID.") from exc
    held_items = [
        h if isinstance(h, HeldEmployeeItem) else HeldEmployeeItem.model_validate(h)
        for h in (payload.held_employee_ids or [])
    ]
    batch = await PaymentBatchService.create_batch_from_run(
        session=db,
        run_id=run_uuid,
        source_account_id=str(payload.source_account_id),
        payment_mode=payload.payment_mode,
        held_employee_ids=held_items,
        notes=payload.notes,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
        payment_date=payload.payment_date,
        validate_source_account=True,
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch created successfully")


@router.get("/payment-batches", summary="List payment batches")
async def list_payment_batches(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    periodId: Optional[uuid.UUID] = Query(None),
    paymentMode: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sortBy: Optional[str] = Query(None),
    sortDir: Optional[str] = Query("desc"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.list_batches(
        session=db,
        company_id=c_uuid,
        period_id=str(periodId) if periodId else None,
        status_filter=status_filter,
        payment_mode=paymentMode,
        search=search,
        page=page,
        limit=limit,
        sort_by=sortBy,
        sort_dir=sortDir,
    )
    ctx = await PaymentBatchService.build_batch_contexts(db, res["items"])
    items = [PaymentBatchService.serialize_batch(b, ctx) for b in res["items"]]
    return _ok(
        {
            "items": items,
            "total": res["total"],
            "page": res["page"],
            "limit": res["limit"],
            "total_pages": res.get("total_pages", 1),
        },
        "Payment batches retrieved successfully",
    )


# ---------------------------------------------------------------------------
# Batch detail, lifecycle, bank files, items, reconciliation, and audit logs
# ---------------------------------------------------------------------------


@router.get("/payment-batches/{batchId}", summary="Get payment batch details and items")
async def get_payment_batch(
    batchId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.get_batch_details(
        session=db,
        batch_id=batchId,
        page=page,
        limit=limit,
        status_filter=status_filter,
        search=search,
        company_id=c_uuid,
    )
    batch = res["batch"]
    items_data = res["items"]
    batch_meta = await _serialize_batch(db, batch)
    serialized_items = await PaymentBatchService._serialize_items(
        db,
        items_data["items"],
        currency=batch_meta["currency"],
        payment_mode=batch_meta.get("payment_mode"),
    )
    val = await PaymentBatchService.validate_batch(db, batchId, company_id=c_uuid, persist=False)
    return _ok(
        {
            "batch": batch_meta,
            "items": {
                "items": serialized_items,
                "total": items_data["total"],
                "page": items_data["page"],
                "limit": items_data["limit"],
            },
            "validationSummary": {
                "totalIssues": len(val["issues"]),
                "errors": val["error_count"],
                "warnings": val["warning_count"],
                "blockingCount": val["blocking_count"],
            },
        },
        "Payment batch details retrieved successfully",
    )


@router.patch("/payment-batches/{batchId}", summary="Update an editable pre-approval payment batch")
async def update_payment_batch(
    batchId: uuid.UUID,
    payload: PaymentBatchUpdateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    batch = await PaymentBatchService.update_draft_batch(
        session=db,
        batch_id=batchId,
        company_id=c_uuid,
        source_account_id=payload.source_account_id,
        payment_mode=payload.payment_mode,
        payment_date=payload.payment_date,
        notes=payload.notes,
        user_id=_uid(claims),
        user_role=_role(claims),
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch updated successfully")


@router.delete("/payment-batches/{batchId}", summary="Delete an eligible draft or rejected payment batch")
async def delete_payment_batch(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.delete_draft_batch(
        session=db,
        batch_id=batchId,
        company_id=c_uuid,
        user_id=_uid(claims),
        user_role=_role(claims),
    )
    return _ok(res, "Payment batch deleted successfully")


@router.post("/payment-batches/{batchId}/cancel", summary="Cancel a pre-submission payment batch")
async def cancel_payment_batch(
    batchId: uuid.UUID,
    payload: Optional[PaymentBatchCancelRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    reason = (payload.reason if payload and payload.reason else None) or "Cancelled by payroll operator"
    batch = await PaymentBatchService.cancel_batch(
        session=db,
        batch_id=batchId,
        reason=reason,
        company_id=c_uuid,
        user_id=_uid(claims),
        user_role=_role(claims),
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch cancelled successfully")


@router.get("/payment-batches/{batchId}/validation", summary="Read-only validation check for payment batch")
async def get_payment_batch_validation(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    val_res = await PaymentBatchService.validate_batch(db, batchId, company_id=c_uuid, persist=False)
    return _ok(val_res, "Payment batch validation retrieved successfully")


@router.post("/payment-batches/{batchId}/validate", summary="Validate payment batch and bank accounts")
async def validate_payment_batch(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    val_res = await PaymentBatchService.validate_batch(
        session=db,
        batch_id=batchId,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
        persist=True,
    )
    return _ok(val_res, "Payment batch validation completed")


@router.post("/payment-batches/{batchId}/submit-for-approval", summary="Submit validated payment batch for approval")
@router.post("/payment-batches/{batchId}/submit-approval", summary="Submit validated payment batch for approval (alias)")
async def submit_payment_batch_for_approval(
    batchId: uuid.UUID,
    payload: Optional[PaymentBatchSubmitForApprovalRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    batch = await PaymentBatchService.submit_for_approval(
        session=db,
        batch_id=batchId,
        remarks=payload.remarks if payload else None,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch submitted for approval")


@router.post("/payment-batches/{batchId}/approve", summary="Approve payment batch")
async def approve_payment_batch(
    batchId: uuid.UUID,
    payload: Optional[PaymentBatchApproveRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    batch = await PaymentBatchService.approve_batch(
        session=db,
        batch_id=batchId,
        user_id=_uid(claims),
        user_role=_role(claims),
        remarks=payload.remarks if payload else None,
        company_id=c_uuid,
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch approved successfully")


@router.post("/payment-batches/{batchId}/reject", summary="Reject payment batch")
async def reject_payment_batch(
    batchId: uuid.UUID,
    payload: PaymentBatchRejectRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    batch = await PaymentBatchService.reject_batch(
        session=db,
        batch_id=batchId,
        user_id=_uid(claims),
        user_role=_role(claims),
        reason=payload.reason,
        company_id=c_uuid,
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch rejected")


@router.get("/payment-batches/{batchId}/bank-file", summary="Get generated bank payment file metadata")
async def get_bank_file_metadata(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    files = await PaymentBatchService.list_bank_files(db, batchId, company_id=c_uuid)
    return _ok(
        {
            "latest": files[0] if files else None,
            "files": files,
        },
        "Bank file metadata retrieved successfully",
    )


@router.post("/payment-batches/{batchId}/bank-file", summary="Generate bank payment file")
async def generate_bank_file(
    batchId: uuid.UUID,
    payload: PaymentBatchBankFileRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    bank_file = await PaymentBatchService.generate_bank_file(
        session=db,
        batch_id=batchId,
        file_format=payload.format,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    files = await PaymentBatchService.list_bank_files(db, batchId, company_id=c_uuid)
    meta = next((f for f in files if f["id"] == str(bank_file.id)), None)
    if meta is None:
        meta = {
            "id": str(bank_file.id),
            "batch_id": str(bank_file.batch_id),
            "file_name": bank_file.file_name,
            "format": bank_file.file_format,
            "file_format": bank_file.file_format,
            "file_size_bytes": bank_file.file_size_bytes,
            "sha256_checksum": bank_file.sha256_checksum,
            "generated_by": {"id": str(_uid(claims) or ""), "name": "Payroll Operator"},
            "generated_at": bank_file.created_at.isoformat() if bank_file.created_at else None,
            "status": bank_file.status,
            "download_url": f"/api/v2/payroll/payment-batches/{batchId}/bank-file/download",
        }
    return _ok(meta, "Bank payment file generated successfully")


@router.get("/payment-batches/{batchId}/bank-file/download", summary="Download generated bank payment file")
async def download_bank_file(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    content_bytes, filename, media_type = await PaymentBatchService.get_latest_bank_file(
        session=db, batch_id=batchId, company_id=c_uuid
    )
    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/payment-batches/{batchId}/submit", summary="Submit payment batch to bank")
async def submit_payment_batch(
    batchId: uuid.UUID,
    payload: PaymentBatchSubmitRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    batch = await PaymentBatchService.submit_batch(
        session=db,
        batch_id=batchId,
        bank_reference_number=payload.bank_reference_number,
        submission_date=payload.submission_date,
        notes=payload.notes,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    return _ok(await _serialize_batch(db, batch), "Payment batch submitted successfully")


@router.get("/payment-batches/{batchId}/items", summary="List employee payment items for batch")
async def list_batch_items(
    batchId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.get_batch_details(
        session=db,
        batch_id=batchId,
        page=page,
        limit=limit,
        status_filter=status_filter,
        search=search,
        company_id=c_uuid,
    )
    batch = res["batch"]
    items_data = res["items"]
    serialized = await PaymentBatchService._serialize_items(
        db,
        items_data["items"],
        currency=getattr(batch, "currency", "INR") or "INR",
        payment_mode=getattr(batch, "payment_mode", None),
    )
    return _ok(
        {
            "items": serialized,
            "total": items_data["total"],
            "page": items_data["page"],
            "limit": items_data["limit"],
        },
        "Payment batch items retrieved successfully",
    )


@router.get("/payment-batches/{batchId}/failed-items", summary="List failed employee payment items for batch")
async def list_failed_batch_items(
    batchId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.get_failed_items(
        session=db,
        batch_id=batchId,
        page=page,
        limit=limit,
        company_id=c_uuid,
    )
    return _ok(res, "Failed payment items retrieved successfully")


@router.get("/payment-batches/{batchId}/items/{itemId}", summary="Get employee payment transaction details")
async def get_batch_item_detail(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    detail = await PaymentBatchService.get_batch_item_detail(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        company_id=c_uuid,
    )
    return _ok(detail, "Payment transaction details retrieved successfully")


@router.post("/payment-batches/{batchId}/items/{itemId}/hold", summary="Hold a specific item in the payment batch")
async def hold_batch_item(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    payload: PaymentBatchItemHoldRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    item = await PaymentBatchService.hold_item(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        reason=payload.reason,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    serialized = (await PaymentBatchService._serialize_items(db, [item]))[0]
    return _ok(serialized, "Item held successfully")


@router.post("/payment-batches/{batchId}/items/{itemId}/release", summary="Release a held item in the payment batch")
async def release_batch_item(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    payload: Optional[PaymentBatchItemReleaseRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    item = await PaymentBatchService.release_item(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        remarks=payload.remarks if payload else None,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    serialized = (await PaymentBatchService._serialize_items(db, [item]))[0]
    return _ok(serialized, "Item released successfully")


@router.post("/payment-batches/{batchId}/items/{itemId}/retry", summary="Retry a failed payment batch item")
async def retry_batch_item(
    batchId: uuid.UUID,
    itemId: uuid.UUID,
    payload: PaymentBatchItemRetryRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    item = await PaymentBatchService.retry_item(
        session=db,
        batch_id=batchId,
        item_id=itemId,
        reason=payload.reason,
        updated_bank_details=payload.updated_bank_details,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    serialized = (await PaymentBatchService._serialize_items(db, [item]))[0]
    return _ok(serialized, "Item queued for retry successfully")


@router.post("/payment-batches/{batchId}/bank-response/preview", summary="Preview bank acknowledgement/reconciliation file")
async def preview_bank_response(
    batchId: uuid.UUID,
    file: UploadFile = File(..., description="Bank payment response file"),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    preview = await PaymentBatchService.preview_bank_response(
        session=db, batch_id=batchId, file=file, company_id=c_uuid
    )
    return _ok(preview, "Bank response preview generated successfully")


@router.post("/payment-batches/{batchId}/bank-response/apply", summary="Apply bank response preview to update transaction states")
async def apply_bank_response(
    batchId: uuid.UUID,
    payload: PaymentBatchBankResponseApplyRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.apply_bank_response(
        session=db,
        batch_id=batchId,
        preview_token=payload.preview_token,
        allow_partial=payload.allow_partial,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    return _ok(res, "Bank response applied successfully")


@router.post("/payment-batches/{batchId}/record-results", summary="Record settlement results (PAID/FAILED) for batch items")
async def record_payment_results(
    batchId: uuid.UUID,
    payload: PaymentBatchRecordResultsRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    res = await PaymentBatchService.record_payment_results(
        session=db,
        batch_id=batchId,
        results=[row.model_dump() for row in payload.results],
        allow_partial=payload.allow_partial,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    return _ok(res, "Payment results recorded successfully")


@router.get("/payment-batches/{batchId}/reconciliation", summary="Get payment batch reconciliation summary")
async def get_payment_batch_reconciliation(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    recon = await PaymentBatchService.get_reconciliation(db, batchId, company_id=c_uuid)
    return _ok(recon, "Reconciliation details retrieved successfully")


@router.post("/payment-batches/{batchId}/reconcile", summary="Reconcile payment batch or apply bank UTR reverse feed")
async def reconcile_payment_batch(
    batchId: uuid.UUID,
    payload: Optional[PaymentBatchReconcileRequest] = None,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    if payload is not None and payload.rows:
        result = await PaymentBatchService.reconcile_bank_feed(
            session=db,
            batch_id=batchId,
            rows=[row.model_dump() for row in payload.rows],
            allow_partial=payload.allow_partial,
            company_id=c_uuid,
            user_id=_uid(claims),
            user_role=_role(claims),
        )
        return _ok(result, "Bank UTR reverse feed reconciled successfully")

    await PaymentBatchService.reconcile_batch(
        session=db,
        batch_id=batchId,
        user_id=_uid(claims),
        user_role=_role(claims),
        notes=payload.notes if payload else None,
        company_id=c_uuid,
    )
    recon = await PaymentBatchService.get_reconciliation(db, batchId, company_id=c_uuid)
    return _ok(recon, "Payment batch reconciled successfully")


@router.post("/payment-batches/{batchId}/retry-failed", summary="Create a linked DRAFT retry batch for all failed items")
async def retry_failed_batch_items(
    batchId: uuid.UUID,
    payload: PaymentBatchRetryFailedRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    retry_batch = await PaymentBatchService.retry_failed_items(
        session=db,
        batch_id=batchId,
        reason=payload.reason,
        payment_mode=payload.payment_mode,
        source_account_id=payload.source_account_id,
        user_id=_uid(claims),
        user_role=_role(claims),
        company_id=c_uuid,
    )
    return _ok(await _serialize_batch(db, retry_batch), "Retry payment batch created successfully")


@router.get("/payment-batches/{batchId}/history", summary="Get payment batch status history")
@router.get("/payment-batches/{batchId}/audit-logs", summary="Get payment batch audit logs")
async def get_payment_batch_audit_logs(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    logs = await PaymentBatchService.get_batch_audit_logs(db, batchId, company_id=c_uuid)
    return _ok(logs, "Payment batch audit history retrieved successfully")


@router.get("/payment-batches/{batchId}/export", summary="Export payment batch disbursement report CSV")
async def export_payment_batch_report(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    content_bytes, filename = await PaymentBatchService.export_batch_report(db, batchId, company_id=c_uuid)
    return Response(
        content=content_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/payment-batches/{batchId}/reconciliation/export",
    summary="Export payment batch reconciliation report CSV",
)
async def export_payment_batch_reconciliation_report(
    batchId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    c_uuid = _require_tenant_id(claims)
    content_bytes, filename = await PaymentBatchService.export_reconciliation_report(
        db, batchId, company_id=c_uuid
    )
    return Response(
        content=content_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
