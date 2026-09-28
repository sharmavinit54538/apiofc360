"""Pydantic schemas for Payment Batches."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


ALLOWED_BANK_FORMATS = ("HDFC_CSV", "ICICI_EXCEL", "SBI_TXT", "GENERIC_NEFT_CSV")


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


class PaymentBatchSubmitRequest(PayrollBaseModel):
    bank_reference_number: str = Field(..., alias="bankReferenceNumber", min_length=2)
    submission_date: date = Field(..., alias="submissionDate")
    notes: Optional[str] = Field(None)


class PaymentBatchItemResponse(PayrollBaseModel):
    id: str
    batch_id: str
    employee_id: str
    amount_paise: int
    status: str
    hold_reason: Optional[str] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    account_holder_name: Optional[str] = None
    transaction_ref: Optional[str] = None
    error_message: Optional[str] = None
    remarks: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PaymentBatchResponse(PayrollBaseModel):
    id: str
    company_id: Optional[str] = None
    run_id: str
    batch_number: str
    source_account_id: str
    payment_mode: str
    status: str
    total_amount_paise: int
    total_records: int
    bank_reference_number: Optional[str] = None
    submission_date: Optional[date] = None
    notes: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    remarks: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    items: Optional[List[PaymentBatchItemResponse]] = None
