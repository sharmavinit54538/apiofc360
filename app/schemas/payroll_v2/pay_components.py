"""Pydantic schemas for Pay Components."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


ALLOWED_TYPES = ("earning", "deduction", "employer_contribution")
ALLOWED_CALC_METHODS = ("flat", "percentage_of_basic", "percentage_of_ctc", "formula")


class PayComponentCreateRequest(PayrollBaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=100)
    type: str = Field(...)
    taxable: bool = Field(True)
    statutory: bool = Field(False)
    calculation_method: str = Field(..., alias="calculationMethod")
    default_percentage: Optional[Decimal] = Field(None, alias="defaultPercentage")
    formula_expr: Optional[str] = Field(None, alias="formulaExpr")
    description: Optional[str] = Field(None)
    effective_date: Optional[date] = Field(None, alias="effectiveDate")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in ALLOWED_TYPES:
            raise ValueError(f"type must be one of: {', '.join(ALLOWED_TYPES)}")
        return clean

    @field_validator("calculation_method")
    @classmethod
    def validate_calc_method(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in ALLOWED_CALC_METHODS:
            raise ValueError(f"calculationMethod must be one of: {', '.join(ALLOWED_CALC_METHODS)}")
        return clean


class PayComponentResponse(PayrollBaseModel):
    id: str
    company_id: Optional[str] = None
    code: str
    name: str
    type: str
    taxable: bool
    statutory: bool
    calculation_method: str
    default_percentage: Optional[Decimal] = None
    formula_expr: Optional[str] = None
    description: Optional[str] = None
    effective_date: date
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
