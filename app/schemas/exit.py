"""Pydantic v2 schemas for the Exit Management module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXIT_REASON_VALUES = {
    "Better Opportunity",
    "Higher Studies",
    "Relocation",
    "Personal Reasons",
    "Health Issues",
    "Retirement",
    "Contract End",
    "Career Change",
    "Other",
}

EXIT_STATUS_VALUES = {
    "DRAFT",
    "SUBMITTED",
    "PENDING_MANAGER_APPROVAL",
    "MANAGER_APPROVED",
    "MANAGER_REJECTED",
    "PENDING_HR_APPROVAL",
    "HR_APPROVED",
    "NOTICE_PERIOD",
    "KNOWLEDGE_TRANSFER_PENDING",
    "ASSET_RETURN_PENDING",
    "NO_DUES_PENDING",
    "EXIT_INTERVIEW_PENDING",
    "FNF_PENDING",
    "COMPLETED",
    "CANCELLED",
}


# ---------------------------------------------------------------------------
# Employee Exit Schemas
# ---------------------------------------------------------------------------

class ResignationRequest(BaseModel):
    last_working_date: date
    reason: str = Field(..., description="Reason for leaving")
    comments: str | None = Field(None, max_length=1000)
    personal_email: EmailStr
    personal_phone: str = Field(..., min_length=10, max_length=20)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if v not in EXIT_REASON_VALUES:
            raise ValueError(f"Reason must be one of: {', '.join(EXIT_REASON_VALUES)}")
        return v

    @field_validator("last_working_date")
    @classmethod
    def validate_date(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("Last working date cannot be in the past.")
        return v


class ExitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    last_working_date: date
    reason: str
    comments: str | None
    personal_email: str
    personal_phone: str
    status: str
    manager_remarks: str | None
    hr_remarks: str | None
    created_at: datetime
    updated_at: datetime


class ExitListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str = Field(..., validation_alias="employee_name")
    employee_code: str = Field(..., validation_alias="employee_code")
    department: str = Field(..., validation_alias="department")
    status: str
    last_working_date: date
    reason: str
    created_at: datetime


class ExitListResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    limit: int
    pages: int


class ExitDashboardStats(BaseModel):
    pending_resignations: int
    pending_manager_approval: int
    pending_hr_approval: int
    employees_in_notice_period: int
    pending_knowledge_transfer: int
    pending_asset_return: int
    pending_no_dues: int
    pending_exit_interviews: int
    pending_final_settlement: int
    completed_exits: int


# ---------------------------------------------------------------------------
# Knowledge Transfer Schemas
# ---------------------------------------------------------------------------

class KTCreate(BaseModel):
    projects_handed_over: str = Field(..., min_length=1)
    documentation_url: str | None = Field(None, max_length=500)
    replacement_assigned_id: uuid.UUID | None = None
    manager_remarks: str | None = Field(None, max_length=1000)
    is_completed: bool = False
    completion_date: date | None = None


class KTResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    projects_handed_over: str
    documentation_url: str | None
    replacement_assigned_id: uuid.UUID | None
    manager_remarks: str | None
    is_completed: bool
    completion_date: date | None


# ---------------------------------------------------------------------------
# Asset Return Schemas
# ---------------------------------------------------------------------------

class AssetReturnCreate(BaseModel):
    asset_name: str = Field(..., min_length=1, max_length=100)
    return_status: str = Field("PENDING")
    return_date: date | None = None
    hr_remarks: str | None = Field(None, max_length=1000)

    @field_validator("return_status")
    @classmethod
    def validate_return_status(cls, v: str) -> str:
        v = v.upper()
        if v not in {"PENDING", "RETURNED"}:
            raise ValueError("return_status must be PENDING or RETURNED")
        return v


class AssetReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    asset_name: str
    return_status: str
    return_date: date | None
    hr_remarks: str | None


# ---------------------------------------------------------------------------
# Clearance Schemas
# ---------------------------------------------------------------------------

class ClearanceUpdate(BaseModel):
    it_clearance: bool | None = None
    hr_clearance: bool | None = None
    finance_clearance: bool | None = None
    admin_clearance: bool | None = None
    manager_clearance: bool | None = None
    security_clearance: bool | None = None


class ClearanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    it_clearance: bool
    hr_clearance: bool
    finance_clearance: bool
    admin_clearance: bool
    manager_clearance: bool
    security_clearance: bool
    overall_status: str


# ---------------------------------------------------------------------------
# Exit Interview Schemas
# ---------------------------------------------------------------------------

class ExitInterviewCreate(BaseModel):
    interview_date: date
    interviewer_name: str = Field(..., min_length=1, max_length=100)
    feedback: str | None = None
    reason_for_leaving: str = Field(..., min_length=1)
    would_rejoin: bool = False
    suggestions: str | None = None
    rating: int = Field(5, ge=1, le=10)


class ExitInterviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    interview_date: date
    interviewer_name: str
    feedback: str | None
    reason_for_leaving: str
    would_rejoin: bool
    suggestions: str | None
    rating: int


# ---------------------------------------------------------------------------
# Full & Final Settlement (FNF) Schemas
# ---------------------------------------------------------------------------

class FnfCreate(BaseModel):
    last_salary: Decimal = Field(Decimal("0.00"), ge=0)
    pending_salary: Decimal = Field(Decimal("0.00"), ge=0)
    leave_encashment: Decimal = Field(Decimal("0.00"), ge=0)
    bonus: Decimal = Field(Decimal("0.00"), ge=0)
    incentives: Decimal = Field(Decimal("0.00"), ge=0)
    recoveries: Decimal = Field(Decimal("0.00"), ge=0)
    notice_recovery: Decimal = Field(Decimal("0.00"), ge=0)
    asset_recovery: Decimal = Field(Decimal("0.00"), ge=0)
    loan_recovery: Decimal = Field(Decimal("0.00"), ge=0)
    other_deductions: Decimal = Field(Decimal("0.00"), ge=0)
    payment_status: str = "PENDING"
    payment_date: date | None = None

    @field_validator("payment_status")
    @classmethod
    def validate_payment_status(cls, v: str) -> str:
        v = v.upper()
        if v not in {"PENDING", "PAID"}:
            raise ValueError("payment_status must be PENDING or PAID")
        return v


class FnfResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    last_salary: Decimal
    pending_salary: Decimal
    leave_encashment: Decimal
    bonus: Decimal
    incentives: Decimal
    recoveries: Decimal
    notice_recovery: Decimal
    asset_recovery: Decimal
    loan_recovery: Decimal
    other_deductions: Decimal
    net_payable_amount: Decimal
    payment_status: str
    payment_date: date | None


# ---------------------------------------------------------------------------
# Exit Document Schemas
# ---------------------------------------------------------------------------

class ExitDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    document_type: str
    file_path: str
    generated_at: datetime
