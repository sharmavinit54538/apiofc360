"""Pydantic schemas and validation for Enterprise Tax Management System."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TaxSlabSchema(BaseModel):
    id: Optional[str] = None
    min_income: float = 0.0
    max_income: Optional[float] = None
    tax_rate: float = 0.0
    flat_amount: float = 0.0


class PayrollTaxSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    tax_name: str
    tax_code: str
    tax_type: str = "INCOME_TAX_NEW"
    description: Optional[str] = None
    financial_year: str = "2026-2027"
    country: str = "IND"
    state: Optional[str] = "TELANGANA"
    calc_type: str = "PROGRESSIVE_SLAB"
    employee_rate: float = 0.0
    employer_rate: float = 0.0
    wage_ceiling: float = 0.0
    std_deduction: float = 75000.0
    is_active: bool = True
    display_order: int = 1
    slabs: List[TaxSlabSchema] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PayrollTaxCreateSchema(BaseModel):
    tax_name: str = Field(..., min_length=2, max_length=100)
    tax_code: str = Field(..., min_length=2, max_length=50)
    tax_type: str = "INCOME_TAX_NEW"
    description: Optional[str] = None
    financial_year: Optional[str] = "2026-2027"
    country: Optional[str] = "IND"
    state: Optional[str] = "TELANGANA"
    calc_type: Optional[str] = "PROGRESSIVE_SLAB"
    employee_rate: Optional[float] = 0.0
    employer_rate: Optional[float] = 0.0
    wage_ceiling: Optional[float] = 0.0
    std_deduction: Optional[float] = 75000.0
    is_active: Optional[bool] = True
    display_order: Optional[int] = 1
    slabs: Optional[List[TaxSlabSchema]] = Field(default_factory=list)

    @field_validator("tax_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.match(r"^[A-Z0-9_]{2,50}$", v):
            raise ValueError("Tax code must contain uppercase letters, numbers, or underscores (e.g. TAX_NEW_REGIME_FY26)")
        return v


class PayrollTaxUpdateSchema(BaseModel):
    tax_name: Optional[str] = None
    tax_code: Optional[str] = None
    tax_type: Optional[str] = None
    description: Optional[str] = None
    financial_year: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    calc_type: Optional[str] = None
    employee_rate: Optional[float] = None
    employer_rate: Optional[float] = None
    wage_ceiling: Optional[float] = None
    std_deduction: Optional[float] = None
    is_active: Optional[bool] = None
    slabs: Optional[List[TaxSlabSchema]] = None


class RecalculateTaxSchema(BaseModel):
    financial_year: Optional[str] = "2026-2027"
    employee_ids: Optional[List[str]] = Field(default_factory=list)
