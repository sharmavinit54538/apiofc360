"""Pydantic schemas for Payroll Cycles."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import Field

from app.schemas.payroll_v2.common import PayrollBaseModel


class PayrollCycleActionRequest(PayrollBaseModel):
    """Payload for reopening or voiding a payroll cycle."""
    reason: str = Field(..., min_length=2, description="Reason for cycle action")


class PayrollCycleCreateRequest(PayrollBaseModel):
    name: str = Field(...)
    frequency: str = Field("MONTHLY")
    period_month: int = Field(...)
    period_year: int = Field(...)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    processing_date: Optional[date] = None
    payment_date: Optional[date] = None


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
    total_employees: int = 0
    total_gross: float = 0.0
    total_deductions: float = 0.0
    total_net: float = 0.0
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
