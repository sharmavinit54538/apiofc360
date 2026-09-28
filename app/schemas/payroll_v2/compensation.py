"""Pydantic schemas for Compensation and Revisions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import Field

from app.schemas.payroll_v2.common import PayrollBaseModel


class CompensationBulkImportApplyRequest(PayrollBaseModel):
    preview_token: str = Field(..., alias="previewToken")


class CompensationRevisionApproveRequest(PayrollBaseModel):
    remarks: Optional[str] = Field(None)


class CompensationRevisionRejectRequest(PayrollBaseModel):
    reason: str = Field(..., description="Mandatory reason for rejecting compensation revision")


class EmployeeCompensationRevisionCreateRequest(PayrollBaseModel):
    new_ctc_annual_paise: int = Field(..., alias="newCtcAnnualPaise", gt=0)
    effective_date: date = Field(..., alias="effectiveDate")
    reason: str = Field(..., min_length=2)
    notes: Optional[str] = Field(None)


class CompensationResponse(PayrollBaseModel):
    id: str
    employee_id: str
    company_id: Optional[str] = None
    ctc_annual_paise: int
    basic_monthly_paise: int = 0
    hra_monthly_paise: int = 0
    special_allowance_monthly_paise: int = 0
    effective_date: date
    status: str
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CompensationRevisionResponse(PayrollBaseModel):
    id: str
    employee_id: str
    company_id: Optional[str] = None
    current_ctc_annual_paise: int
    new_ctc_annual_paise: int
    effective_date: date
    reason: str
    notes: Optional[str] = None
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    remarks: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BulkImportRowValidation(PayrollBaseModel):
    row_number: int
    employee_id: Optional[str] = None
    ctc_annual_paise: Optional[int] = None
    is_valid: bool
    errors: List[str] = Field(default_factory=list)


class BulkImportPreviewResponse(PayrollBaseModel):
    preview_token: str = Field(..., alias="previewToken")
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: List[BulkImportRowValidation]
