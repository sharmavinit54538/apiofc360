"""Pydantic v2 schemas for the Exit Management module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Constants - Use centralized state machine values
# ---------------------------------------------------------------------------

from app.core.exit_state_machine import ExitStatus, ACTIVE_STATUSES, TERMINAL_STATUSES

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

# Canonical status values from state machine
EXIT_STATUS_VALUES = {s.value for s in ExitStatus}
ACTIVE_EXIT_STATUS_VALUES = {s.value for s in ACTIVE_STATUSES}
TERMINAL_EXIT_STATUS_VALUES = {s.value for s in TERMINAL_STATUSES}


# ---------------------------------------------------------------------------
# Employee Exit Schemas
# ---------------------------------------------------------------------------

# Exit type values for HR-initiated exits
EXIT_TYPE_VALUES = {
    "resignation",
    "termination",
    "retirement",
    "contract_end",
    "layoff",
    "mutual_separation",
    "probation_failure",
    "medical_separation",
    "death",
}


class ExitInitiationRequest(BaseModel):
    """Base request for any exit initiation (employee resignation or HR-initiated)."""
    employee_id: uuid.UUID | None = None  # Required for HR-initiated, ignored for employee resignation
    last_working_date: date
    exit_type: str = Field("resignation", description="Type of exit")
    reason: str = Field(..., description="Reason for leaving")
    comments: str | None = Field(None, max_length=1000)
    personal_email: EmailStr | None = None  # Required for resignation, optional for HR-initiated
    personal_phone: str | None = Field(None, min_length=10, max_length=20)  # Required for resignation, optional for HR-initiated
    notice_period_days_required: int | None = None  # Override default notice period
    notice_waived: bool = False
    notice_buyout: bool = False
    effective_date: date | None = None  # For termination/retirement - legal effective date

    @field_validator("exit_type")
    @classmethod
    def validate_exit_type(cls, v: str) -> str:
        if v not in EXIT_TYPE_VALUES:
            raise ValueError(f"exit_type must be one of: {', '.join(EXIT_TYPE_VALUES)}")
        return v

    @field_validator("last_working_date")
    @classmethod
    def validate_date(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("Last working date cannot be in the past.")
        return v

    @field_validator("effective_date")
    @classmethod
    def validate_effective_date(cls, v: date | None, info) -> date | None:
        if v is not None:
            lwd = info.data.get("last_working_date")
            if lwd and v > lwd:
                raise ValueError("Effective date cannot be after last working date.")
        return v


class ResignationRequest(ExitInitiationRequest):
    """Employee resignation request - employee_id is derived from authenticated user."""
    exit_type: str = Field("resignation", description="Type of exit", frozen=True)
    personal_email: EmailStr
    personal_phone: str = Field(..., min_length=10, max_length=20)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if v not in EXIT_REASON_VALUES:
            raise ValueError(f"Reason must be one of: {', '.join(EXIT_REASON_VALUES)}")
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
    exit_type: str = "resignation"
    effective_date: date | None = None
    initiated_by: uuid.UUID | None = None
    initiated_by_role: str | None = None


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
    """FNF settlement creation - payment_status is NOT settable here.
    Payment status can only be set via authorized payment confirmation flow."""
    last_salary: Decimal = Field(Decimal("0.00"), ge=0)
    pending_salary: Decimal = Field(Decimal("0.00"), ge=0)
    leave_encashment: Decimal = Field(Decimal("0.00"), ge=0)
    gratuity: Decimal = Field(Decimal("0.00"), ge=0)
    bonus: Decimal = Field(Decimal("0.00"), ge=0)
    incentives: Decimal = Field(Decimal("0.00"), ge=0)
    recoveries: Decimal = Field(Decimal("0.00"), ge=0)
    notice_recovery: Decimal = Field(Decimal("0.00"), ge=0)
    asset_recovery: Decimal = Field(Decimal("0.00"), ge=0)
    loan_recovery: Decimal = Field(Decimal("0.00"), ge=0)
    other_deductions: Decimal = Field(Decimal("0.00"), ge=0)
    # payment_status and payment_date are intentionally omitted - set only via payment confirmation
    settlement_breakup: dict | None = None


class FnfResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exit_id: uuid.UUID
    last_salary: Decimal
    pending_salary: Decimal
    leave_encashment: Decimal
    gratuity: Decimal = Decimal("0.00")
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
    status: str = "DRAFT"
    settlement_breakup: dict | None = None
    statement_path: str | None = None
    statement_hash: str | None = None
    settled_at: datetime | None = None
    generated_letters_json: list | None = None


class FnfPreviewResponse(BaseModel):
    exit_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    joining_date: date | None
    last_working_date: date
    tenure_years: float
    basic_monthly: float
    da_monthly: float = 0.0
    gross_monthly: float = 0.0
    last_salary: float
    base_pending_salary: float = 0.0
    arrears: float = 0.0
    pending_salary: float
    leave_encashment: float
    unused_leave_days: float
    leave_breakup: list[dict] = Field(default_factory=list)
    gratuity: float
    gratuity_ceiling: float = 2000000.0
    bonus: float
    incentives: float
    recoveries: float
    notice_recovery: float
    required_notice_days: int
    actual_notice_days: int
    notice_shortfall_days: int = 0
    notice_payout: float = 0.0
    notice_waived: bool = False
    notice_buyout: bool = False
    asset_recovery: float
    loan_recovery: float
    other_deductions: float
    total_earnings: float
    total_deductions: float
    net_payable_amount: float
    payment_status: str


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
