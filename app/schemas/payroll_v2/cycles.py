"""Pydantic schemas for Payroll Cycles."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import Field, model_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


class PayrollCycleActionRequest(PayrollBaseModel):
    """Payload for reopening or voiding a payroll cycle."""
    reason: str = Field(..., min_length=2, description="Reason for cycle action")


class PayrollCycleLockRequest(PayrollBaseModel):
    """Optional payload when locking a payroll cycle."""
    reason: Optional[str] = Field(None, max_length=500, description="Optional reason for locking period")


class PayrollCycleCreateRequest(PayrollBaseModel):
    name: str = Field(...)
    frequency: str = Field("MONTHLY")
    period_month: Optional[int] = Field(None, alias="periodMonth", ge=1, le=12)
    period_year: Optional[int] = Field(None, alias="periodYear", ge=2000, le=2100)
    start_date: Optional[date] = Field(None, alias="startDate")
    end_date: Optional[date] = Field(None, alias="endDate")
    processing_date: Optional[date] = Field(None, alias="processingDate")
    payment_date: Optional[date] = Field(None, alias="paymentDate")
    pay_date: Optional[date] = Field(None, alias="payDate")
    regularisation_deadline: Optional[datetime] = Field(None, alias="regularisationDeadline")
    remarks: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            mapping = (
                ("period_month", "periodMonth"),
                ("period_year", "periodYear"),
                ("start_date", "startDate"),
                ("end_date", "endDate"),
                ("processing_date", "processingDate"),
                ("payment_date", "paymentDate"),
                ("pay_date", "payDate"),
                ("regularisation_deadline", "regularisationDeadline"),
            )
            for snake, camel in mapping:
                if snake in data and data.get(camel) is None:
                    data[camel] = data[snake]
        return data

    @model_validator(mode="after")
    def _derive_and_validate(self) -> "PayrollCycleCreateRequest":
        if self.payment_date is None and self.pay_date is not None:
            self.payment_date = self.pay_date
        if self.start_date and not self.period_month:
            self.period_month = self.start_date.month
        if self.start_date and not self.period_year:
            self.period_year = self.start_date.year
        if not self.period_month or not self.period_year:
            raise ValueError("period_month and period_year (or start_date to derive them) are required.")
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        return self


class PayrollCycleResponse(PayrollBaseModel):
    id: str
    company_id: Optional[str] = None
    name: str
    frequency: str
    period_month: int
    period_year: int
    status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    processing_date: Optional[date] = None
    payment_date: Optional[date] = None
    is_active: bool = False
    is_locked: bool = False
    regularisation_deadline: Optional[datetime] = None
    attendance_locked_at: Optional[datetime] = None
    attendance_locked_by: Optional[str] = None
    unlock_reason: Optional[str] = None
    total_employees: int = 0
    total_gross: float = 0.0
    total_deductions: float = 0.0
    total_net: float = 0.0
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
