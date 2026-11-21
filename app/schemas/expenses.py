"""Validated expense contracts shared by API v1 and v2."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

ExpenseStatus = Literal["draft", "submitted", "approved", "rejected", "changes_requested", "paid"]
Money = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
PaymentMethod = Literal["bank_transfer", "upi", "cash", "cheque", "card", "payroll", "other"]


class ExpenseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("amount", mode="before", check_fields=False)
    @classmethod
    def reject_boolean_amount(cls, value):
        if isinstance(value, bool):
            raise ValueError("Amount must be a monetary value.")
        return value

    @field_validator("currency", mode="before", check_fields=False)
    @classmethod
    def normalize_currency(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("category", mode="before", check_fields=False)
    @classmethod
    def normalize_category(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("receipt_url", check_fields=False)
    @classmethod
    def validate_receipt(cls, value):
        if value is not None:
            HttpUrl(value)
        return value


class ExpenseCreate(ExpenseInput):
    category: str = Field(min_length=1, max_length=100, examples=["travel"])
    amount: Money
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    expense_date: date
    description: str = Field(min_length=1, max_length=500)
    merchant: str | None = Field(default=None, min_length=1, max_length=255)
    receipt_url: str | None = Field(default=None, max_length=500)
    project_id: str | None = Field(default=None, min_length=1, max_length=100)


class ExpenseUpdate(ExpenseInput):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    amount: Money | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    expense_date: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=500)
    merchant: str | None = Field(default=None, min_length=1, max_length=255)
    receipt_url: str | None = Field(default=None, max_length=500)
    project_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one expense field is required.")
        for name in self.model_fields_set & {"category", "amount", "currency", "expense_date", "description"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class ExpenseApproval(ExpenseInput):
    comment: str | None = Field(default=None, min_length=1, max_length=500)


class ExpenseReason(ExpenseInput):
    reason: str = Field(min_length=1, max_length=500)


class ExpensePayment(ExpenseInput):
    payment_reference: str = Field(min_length=1, max_length=128)
    payment_method: PaymentMethod
    paid_at: AwareDatetime

    @field_validator("paid_at")
    @classmethod
    def payment_not_in_future(cls, value):
        if value > datetime.now(timezone.utc):
            raise ValueError("Payment timestamp cannot be in the future.")
        return value


class ExpenseStatusUpdate(ExpenseInput):
    status: ExpenseStatus
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    payment_reference: str | None = Field(default=None, min_length=1, max_length=128)
    payment_method: PaymentMethod | None = None
    paid_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_transition_details(self):
        if self.status in {"rejected", "changes_requested"} and not self.reason:
            raise ValueError("A reason is required for rejection or a change request.")
        if self.status == "paid":
            ExpensePayment.model_validate({name: getattr(self, name) for name in ("payment_reference", "payment_method", "paid_at")})
        elif any(getattr(self, name) is not None for name in ("payment_reference", "payment_method", "paid_at")):
            raise ValueError("Payment details are allowed only for a paid transition.")
        return self


class ExpenseFilters(ExpenseInput):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    status: ExpenseStatus | None = None
    employee_id: UUID | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = Field(default=None, min_length=1, max_length=200)
    sort_by: Literal["created_at", "updated_at", "expense_date", "amount", "category", "status"] = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def valid_date_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to.")
        return self


class ExpenseEmployee(BaseModel):
    id: UUID
    employee_code: str
    name: str
    department: str
    designation: str


class ExpenseResponse(BaseModel):
    id: UUID
    organization_id: UUID
    employee_id: UUID
    employee: ExpenseEmployee
    category: str
    amount: Decimal
    currency: str
    expense_date: date
    description: str | None
    merchant: str | None
    receipt_url: str | None
    project_id: str | None
    status: str
    approved_by: UUID | None
    approved_at: datetime | None
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    payment_reference: str | None
    payment_method: str | None
    paid_at: datetime | None
    paid_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ExpensePage(BaseModel):
    items: list[ExpenseResponse]
    total: int
    page: int
    limit: int
    pages: int
    has_next: bool
    has_previous: bool
