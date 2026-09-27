"""Pydantic schemas for Payroll Reports."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


ALLOWED_REPORT_FORMATS = ("csv", "xlsx")


class PayrollReportExportRequest(PayrollBaseModel):
    format: str = Field("csv")
    filters: Optional[dict[str, Any]] = Field(default_factory=dict)

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in ALLOWED_REPORT_FORMATS:
            raise ValueError(f"format must be one of: {', '.join(ALLOWED_REPORT_FORMATS)}")
        return clean


class PayrollReportRow(PayrollBaseModel):
    employee_id: str
    employee_name: str
    department: Optional[str] = None
    designation: Optional[str] = None
    gross_earnings: float
    total_deductions: float
    net_pay: float
    payment_status: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class PayrollReportResponse(PayrollBaseModel):
    report_key: str
    total_records: int
    data: List[dict[str, Any]] = Field(default_factory=list)
