"""Pydantic schemas for Payroll Runs (v1 & v2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


class PayrollRunCreateRequest(PayrollBaseModel):
    """Payload to trigger a new payroll run for a period."""
    period_id: str = Field(..., alias="periodId")


class PayrollRunApproveRequest(PayrollBaseModel):
    """Payload to approve a payroll run."""
    comments: Optional[str] = Field(None)


class PayrollRunFinalizeRequest(PayrollBaseModel):
    """Payload to finalize and optionally lock a payroll run."""
    notes: Optional[str] = Field(None)
    lock: bool = Field(True)


class PayrollRunRejectRequest(PayrollBaseModel):
    """Payload to reject a payroll run — reason required."""
    reason: str = Field(..., description="Mandatory reason for rejection")
    comments: Optional[str] = Field(None)


class PayrollRunSendBackRequest(PayrollBaseModel):
    """Payload to send back a payroll run for correction."""
    reason: Optional[str] = Field(None)
    comments: Optional[str] = Field(None)


class PayrollRunPayslipGenerateRequest(PayrollBaseModel):
    """Payload for batch payslip generation."""
    employee_ids: Optional[List[str]] = Field(default_factory=list, alias="employeeIds")
    force: bool = Field(False)
    format: str = Field("pdf")


class HeldEmployeeItem(PayrollBaseModel):
    employee_id: str = Field(..., alias="employeeId")
    reason: Optional[str] = Field(None)


class PayrollRunPaymentBatchCreateRequest(PayrollBaseModel):
    """Payload to create a payment batch from a finalized payroll run."""
    source_account_id: str = Field(..., alias="sourceAccountId")
    payment_mode: str = Field(..., alias="paymentMode")  # NEFT | RTGS | IMPS | UPI
    held_employee_ids: Optional[List[HeldEmployeeItem]] = Field(default_factory=list, alias="heldEmployeeIds")
    notes: Optional[str] = Field(None)

    @field_validator("payment_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        mode = v.upper()
        if mode not in ("NEFT", "RTGS", "IMPS", "UPI"):
            raise ValueError("paymentMode must be one of: NEFT, RTGS, IMPS, UPI")
        return mode


class PayrollRunEmployeeResponse(PayrollBaseModel):
    id: str
    run_id: str
    employee_id: str
    gross_earnings_paise: int
    total_deductions_paise: int
    net_pay_paise: int
    paid_days: float
    lop_days: float
    validation_status: str
    validation_messages: Optional[List[str]] = None
    status: str
    earnings_breakup: Optional[dict[str, Any]] = None
    deductions_breakup: Optional[dict[str, Any]] = None


class PayrollRunResponse(PayrollBaseModel):
    id: str
    company_id: Optional[str] = None
    period_id: Optional[str] = None
    run_number: Optional[str] = None
    period_month: int
    period_year: int
    status: str
    total_employees: int
    total_gross: float
    total_deductions: float
    total_net: float
    total_gross_paise: int = 0
    total_deductions_paise: int = 0
    total_net_paise: int = 0
    validation_status: str = "PENDING"
    validation_errors: Optional[Any] = None
    validation_notes: Optional[str] = None
    is_locked: bool = False
    notes: Optional[str] = None
    comments: Optional[str] = None
    job_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
