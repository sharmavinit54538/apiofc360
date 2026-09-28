"""Pydantic schemas for Payroll Periods."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional
from pydantic import Field, model_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


class PayrollPeriodCreateRequest(PayrollBaseModel):
    """Schema for creating a payroll period accepting both snake_case and camelCase keys."""
    name: str = Field(..., description="Period name (e.g. 'September 2026')")
    start_date: Optional[date] = Field(None, alias="startDate")
    end_date: Optional[date] = Field(None, alias="endDate")
    pay_date: Optional[date] = Field(None, alias="payDate")

    period_month: Optional[int] = Field(None, alias="periodMonth")
    period_year: Optional[int] = Field(None, alias="periodYear")
    company_id: Optional[str] = Field(None, alias="companyId")
    remarks: Optional[str] = Field(None)

    @model_validator(mode="before")
    @classmethod
    def normalize_dates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Fallback if snake_case provided directly when alias is camelCase
            if "start_date" in data and not data.get("startDate"):
                data["startDate"] = data["start_date"]
            if "end_date" in data and not data.get("endDate"):
                data["endDate"] = data["end_date"]
            if "pay_date" in data and not data.get("payDate"):
                data["payDate"] = data["pay_date"]
            if "period_month" in data and not data.get("periodMonth"):
                data["periodMonth"] = data["period_month"]
            if "period_year" in data and not data.get("periodYear"):
                data["periodYear"] = data["period_year"]
            if "company_id" in data and not data.get("companyId"):
                data["companyId"] = data["company_id"]
        return data

    @model_validator(mode="after")
    def validate_required_dates(self) -> PayrollPeriodCreateRequest:
        if not self.start_date:
            raise ValueError("start_date or startDate is required")
        if not self.end_date:
            raise ValueError("end_date or endDate is required")
        if not self.pay_date:
            raise ValueError("pay_date or payDate is required")
        return self


class PayrollPeriodResponse(PayrollBaseModel):
    id: str
    company_id: Optional[str] = None
    name: str
    start_date: date
    end_date: date
    pay_date: date
    period_month: int
    period_year: int
    status: str
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
