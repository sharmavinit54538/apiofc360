"""Pydantic schemas and validation for Payroll Cycle Management."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class CycleLocksSchema(BaseModel):
    attendance: bool = False
    leaves: bool = False
    overtime: bool = False
    components: bool = False
    tax: bool = False
    payslips: bool = False


class CycleAutomationSchema(BaseModel):
    auto_generation: bool = True
    auto_payslip: bool = True
    auto_calc: bool = True
    auto_email: bool = True
    auto_whatsapp: bool = False
    auto_rollover: bool = True


class PayCycleSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    name: str = "Monthly Payroll Cycle"
    frequency: str = "MONTHLY"  # WEEKLY | BI_WEEKLY | SEMI_MONTHLY | MONTHLY | QUARTERLY | YEARLY
    period_month: int = 1
    period_year: int = 2026

    status: str = "DRAFT"  # DRAFT | SCHEDULED | RUNNING | LOCKED | PROCESSING | COMPLETED | CANCELLED | ARCHIVED

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    processing_date: Optional[str] = None
    payment_date: Optional[str] = None
    payslip_generation_date: Optional[str] = None

    attendance_lock_date: Optional[str] = None
    leave_lock_date: Optional[str] = None
    overtime_lock_date: Optional[str] = None
    tax_calculation_date: Optional[str] = None
    bonus_processing_date: Optional[str] = None

    is_active: bool = False
    is_locked: bool = False

    locks: Optional[CycleLocksSchema] = Field(default_factory=CycleLocksSchema)
    automation: Optional[CycleAutomationSchema] = Field(default_factory=CycleAutomationSchema)

    total_employees: int = 0
    total_gross: float = 0.0
    total_deductions: float = 0.0
    total_net: float = 0.0

    remarks: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PayCycleCreateSchema(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    frequency: str = "MONTHLY"
    period_month: int = Field(1, ge=1, le=12)
    period_year: int = Field(2026, ge=2020, le=2050)
    start_date: str
    end_date: str
    processing_date: str
    payment_date: str
    payslip_generation_date: Optional[str] = None
    attendance_lock_date: Optional[str] = None
    leave_lock_date: Optional[str] = None
    overtime_lock_date: Optional[str] = None
    locks: Optional[Dict[str, bool]] = None
    automation: Optional[Dict[str, bool]] = None
    remarks: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self) -> PayCycleCreateSchema:
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError("Start Date must be earlier than End Date")
        if self.payment_date and self.processing_date and self.payment_date < self.processing_date:
            raise ValueError("Payment Date must be on or after Salary Processing Date")
        if self.attendance_lock_date and self.processing_date and self.attendance_lock_date > self.processing_date:
            raise ValueError("Attendance Lock Date must be on or before Processing Date")
        return self


class PayCycleUpdateSchema(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    period_month: Optional[int] = None
    period_year: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    processing_date: Optional[str] = None
    payment_date: Optional[str] = None
    payslip_generation_date: Optional[str] = None
    attendance_lock_date: Optional[str] = None
    leave_lock_date: Optional[str] = None
    overtime_lock_date: Optional[str] = None
    status: Optional[str] = None
    locks: Optional[Dict[str, bool]] = None
    automation: Optional[Dict[str, bool]] = None
    remarks: Optional[str] = None


class PayCycleActionSchema(BaseModel):
    reason: Optional[str] = "Action performed on payroll cycle"


class PayCycleLockSchema(BaseModel):
    lock_attendance: Optional[bool] = None
    lock_leaves: Optional[bool] = None
    lock_overtime: Optional[bool] = None
    lock_components: Optional[bool] = None
    lock_tax: Optional[bool] = None
    lock_payslips: Optional[bool] = None
    reason: Optional[str] = "Payroll locks modified"
