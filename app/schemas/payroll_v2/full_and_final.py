"""Pydantic schemas for Full & Final Settlement."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


ALLOWED_EXIT_TYPES = ("resignation", "termination", "retirement", "layoff", "contract_end")


class ExitDetails(PayrollBaseModel):
    resignation_date: date = Field(..., alias="resignationDate")
    last_working_date: date = Field(..., alias="lastWorkingDate")
    exit_type: str = Field(..., alias="exitType")
    reason: str = Field(...)
    notice_period_days_required: int = Field(..., alias="noticePeriodDaysRequired")
    notice_period_days_served: int = Field(..., alias="noticePeriodDaysServed")
    shortfall_days: int = Field(..., alias="shortfallDays")

    @field_validator("exit_type")
    @classmethod
    def validate_exit_type(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in ALLOWED_EXIT_TYPES:
            raise ValueError(f"exitType must be one of: {', '.join(ALLOWED_EXIT_TYPES)}")
        return clean


class FullAndFinalCreateRequest(PayrollBaseModel):
    employee_id: str = Field(..., alias="employeeId")
    exit_details: ExitDetails = Field(..., alias="exitDetails")
    remarks: Optional[str] = Field(None)


class FullAndFinalApproveRequest(PayrollBaseModel):
    remarks: Optional[str] = Field(None)


class FullAndFinalFinalizeRequest(PayrollBaseModel):
    notes: Optional[str] = Field(None)


class FullAndFinalRejectRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2, description="Reason for rejection")


class FullAndFinalResponse(PayrollBaseModel):
    id: str
    employee_id: str
    company_id: Optional[str] = None
    resignation_date: date
    last_working_date: date
    exit_type: str
    reason: str
    notice_period_days_required: int
    notice_period_days_served: int
    shortfall_days: int
    status: str
    net_payable_paise: int = 0
    remarks: Optional[str] = None
    notes: Optional[str] = None
    statement_path: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    finalized_by: Optional[str] = None
    finalized_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
