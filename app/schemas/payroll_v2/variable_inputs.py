"""Pydantic schemas for Variable Inputs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


ALLOWED_VARIABLE_TYPES = (
    "overtime", "bonus", "incentive", "commission", "reimbursement",
    "deduction", "advance_recovery", "lop", "other"
)


class VariableInputCreateRequest(PayrollBaseModel):
    employee_id: str = Field(..., alias="employeeId")
    period_id: str = Field(..., alias="periodId")
    type: str = Field(...)
    amount_paise: int = Field(..., alias="amountPaise")
    description: str = Field(..., min_length=2)
    units: Optional[Decimal] = Field(None)
    rate_per_unit_paise: Optional[int] = Field(None, alias="ratePerUnitPaise")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in ALLOWED_VARIABLE_TYPES:
            raise ValueError(f"type must be one of: {', '.join(ALLOWED_VARIABLE_TYPES)}")
        return clean


class VariableInputBulkApplyRequest(PayrollBaseModel):
    preview_token: str = Field(..., alias="previewToken")


class VariableInputApproveRequest(PayrollBaseModel):
    remarks: Optional[str] = Field(None)


class VariableInputRejectRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2, description="Reason for rejection")


class VariableInputResponse(PayrollBaseModel):
    id: str
    employee_id: str
    period_id: str
    company_id: Optional[str] = None
    type: str
    amount_paise: int
    units: Optional[Decimal] = None
    rate_per_unit_paise: Optional[int] = None
    description: str
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    remarks: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
