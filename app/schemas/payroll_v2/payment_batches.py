"""Pydantic schemas for Payment Batches."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


def _coerce_date_value(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    raw = str(v).strip()
    if not raw:
        return None
    if "T" in raw:
        try:
            iso = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(iso).date()
        except ValueError:
            pass
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {v!r}") from exc


ALLOWED_BANK_FORMATS = (
    "ICICI_CORPORATE", "ICICI_CORPORATE_CSV", "HDFC_ENET_CSV", "SBI_CMP_TXT", "GENERIC_NEFT_RTGS_CSV",
    # Backward-compatible aliases used by existing payroll workers/clients.
    "HDFC_CSV", "ICICI_EXCEL", "SBI_TXT", "GENERIC_NEFT_CSV",
)


class PaymentBatchApproveRequest(PayrollBaseModel):
    remarks: Optional[str] = Field(None)


class PaymentBatchBankFileRequest(PayrollBaseModel):
    format: str = Field(...)

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        clean = v.upper().strip()
        if clean not in ALLOWED_BANK_FORMATS:
            raise ValueError(f"format must be one of: {', '.join(ALLOWED_BANK_FORMATS)}")
        return clean


class PaymentBatchBankResponseApplyRequest(PayrollBaseModel):
    preview_token: str = Field(..., alias="previewToken")
    allow_partial: bool = Field(False, alias="allowPartial")


class BankReconciliationRow(PayrollBaseModel):
    item_id: Optional[str] = Field(None, alias="itemId")
    account_number: Optional[str] = Field(None, alias="accountNumber")
    transaction_ref: Optional[str] = Field(None, alias="transactionRef")
    status: str
    utr_number: Optional[str] = Field(None, alias="utrNumber")
    error_message: Optional[str] = Field(None, alias="errorMessage")


class PaymentBatchReconcileRequest(PayrollBaseModel):
    rows: Optional[List[BankReconciliationRow]] = None
    allow_partial: bool = Field(False, alias="allowPartial")
    notes: Optional[str] = Field(None)


class PaymentBatchItemHoldRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2)


class PaymentBatchItemReleaseRequest(PayrollBaseModel):
    remarks: Optional[str] = Field(None)


class UpdatedBankDetails(PayrollBaseModel):
    account_number: Optional[str] = Field(None, alias="accountNumber")
    ifsc_code: Optional[str] = Field(None, alias="ifscCode")
    account_holder_name: Optional[str] = Field(None, alias="accountHolderName")


class PaymentBatchItemRetryRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2)
    updated_bank_details: Optional[UpdatedBankDetails] = Field(None, alias="updatedBankDetails")


class PaymentBatchRejectRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2)


class PaymentBatchCancelRequest(PayrollBaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class PaymentBatchSubmitRequest(PayrollBaseModel):
    bank_reference_number: str = Field(..., alias="bankReferenceNumber", min_length=2)
    submission_date: date = Field(..., alias="submissionDate")
    notes: Optional[str] = Field(None)

    @field_validator("submission_date", mode="before")
    @classmethod
    def parse_submission_date(cls, v: Any) -> date:
        parsed = _coerce_date_value(v)
        if parsed is None:
            raise ValueError("submissionDate is required")
        return parsed


class PaymentBatchCreateRequest(PayrollBaseModel):
    run_id: str = Field(..., alias="runId")
    source_account_id: str = Field(..., alias="sourceAccountId")
    payment_mode: str = Field(..., alias="paymentMode")
    held_employee_ids: Optional[List[Any]] = Field(default_factory=list, alias="heldEmployeeIds")
    payment_date: Optional[date] = Field(None, alias="paymentDate")
    notes: Optional[str] = Field(None)

    @field_validator("payment_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        mode = v.upper().strip()
        if mode not in ("NEFT", "RTGS", "IMPS", "UPI"):
            raise ValueError("paymentMode must be one of: NEFT, RTGS, IMPS, UPI")
        return mode

    @field_validator("payment_date", mode="before")
    @classmethod
    def parse_payment_date(cls, v: Any) -> Optional[date]:
        return _coerce_date_value(v)


class PaymentBatchUpdateRequest(PayrollBaseModel):
    source_account_id: Optional[str] = Field(None, alias="sourceAccountId")
    payment_mode: Optional[str] = Field(None, alias="paymentMode")
    payment_date: Optional[date] = Field(None, alias="paymentDate")
    notes: Optional[str] = Field(None)

    @field_validator("payment_date", mode="before")
    @classmethod
    def parse_payment_date(cls, v: Any) -> Optional[date]:
        return _coerce_date_value(v)


class PaymentBatchSubmitForApprovalRequest(PayrollBaseModel):
    remarks: Optional[str] = Field(None)


class PaymentBatchResultItem(PayrollBaseModel):
    item_id: Optional[str] = Field(None, alias="itemId")
    employee_id: Optional[str] = Field(None, alias="employeeId")
    status: str
    paid_amount_paise: Optional[int] = Field(None, alias="paidAmountPaise")
    transaction_ref: Optional[str] = Field(None, alias="transactionRef")
    utr_number: Optional[str] = Field(None, alias="utrNumber")
    payment_date: Optional[datetime] = Field(None, alias="paymentDate")
    failure_code: Optional[str] = Field(None, alias="failureCode")
    error_message: Optional[str] = Field(None, alias="errorMessage")
    remarks: Optional[str] = None


class PaymentBatchRecordResultsRequest(PayrollBaseModel):
    results: List[PaymentBatchResultItem] = Field(..., min_length=1)
    allow_partial: bool = Field(True, alias="allowPartial")


class PaymentBatchReconcileConfirmRequest(PayrollBaseModel):
    rows: Optional[List[BankReconciliationRow]] = None
    allow_partial: bool = Field(False, alias="allowPartial")
    notes: Optional[str] = Field(None)


class PaymentBatchRetryFailedRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2)
    payment_mode: Optional[str] = Field(None, alias="paymentMode")
    source_account_id: Optional[str] = Field(None, alias="sourceAccountId")


class PaymentBatchItemResponse(PayrollBaseModel):
    id: str
    batch_id: str
    employee_id: str
    employee_code: Optional[str] = None
    employee_name: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    bank_name: Optional[str] = None
    amount_paise: int
    payable_amount_paise: Optional[int] = None
    paid_amount_paise: int = 0
    status: str
    hold_reason: Optional[str] = None
    account_number_masked: Optional[str] = None
    ifsc_code: Optional[str] = None
    account_holder_name: Optional[str] = None
    transaction_ref: Optional[str] = None
    payment_reference: Optional[str] = None
    utr_number: Optional[str] = None
    payment_date: Optional[datetime] = None
    reconciled_at: Optional[datetime] = None
    reconciliation_status: str = "PENDING"
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    remarks: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PaymentBatchResponse(PayrollBaseModel):
    id: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    run_id: str
    run_number: Optional[str] = None
    payroll_run_number: Optional[str] = None
    period_id: Optional[str] = None
    period_name: Optional[str] = None
    payroll_period: Optional[str] = None
    batch_number: str
    source_account_id: str
    payment_mode: str
    currency: str = "INR"
    status: str
    gross_amount_paise: int = 0
    held_amount_paise: int = 0
    total_amount_paise: int
    payable_amount_paise: int = 0
    paid_amount_paise: int = 0
    failed_amount_paise: int = 0
    pending_amount_paise: int = 0
    outstanding_amount_paise: int = 0
    total_records: int
    employee_count: int = 0
    bank_reference_number: Optional[str] = None
    submission_date: Optional[date] = None
    bank_file_id: Optional[str] = None
    notes: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reconciled_by: Optional[str] = None
    reconciled_at: Optional[datetime] = None
    remarks: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    items: Optional[List[PaymentBatchItemResponse]] = None


class PaymentDashboardSummaryResponse(PayrollBaseModel):
    total_batches: int = 0
    draft_batches: int = 0
    validating_batches: int = 0
    validation_failed_batches: int = 0
    validated_batches: int = 0
    pending_approval_batches: int = 0
    approved_batches: int = 0
    rejected_batches: int = 0
    file_generated_batches: int = 0
    submitted_to_bank_batches: int = 0
    processing_batches: int = 0
    partially_paid_batches: int = 0
    paid_batches: int = 0
    failed_batches: int = 0
    cancelled_batches: int = 0
    reconciled_batches: int = 0
    awaiting_approval_batches: int = 0
    in_banking_processing_batches: int = 0
    total_payable_amount_paise: int = 0
    total_paid_amount_paise: int = 0
    total_held_amount_paise: int = 0
    total_failed_amount_paise: int = 0
    outstanding_payment_amount_paise: int = 0
    reconciliation_percentage: float = 0.0
    currency: str = "INR"
    timezone: str = "Asia/Kolkata"
