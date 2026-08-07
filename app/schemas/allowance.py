"""Pydantic schemas and validation for Allowance Management System."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class AllowanceSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    name: str
    display_name: Optional[str] = None
    code: str
    description: Optional[str] = None
    category: str = "SPECIAL"

    earning_type: str = "FIXED"
    is_variable: bool = False
    frequency: str = "MONTHLY"
    is_recurring: bool = True

    calc_type: str = "FIXED"
    formula_expr: Optional[str] = None
    default_amount: float = 0.0
    min_limit: float = 0.0
    max_limit: float = 0.0
    currency: str = "INR"

    taxability_type: str = "TAXABLE"  # TAXABLE | NON_TAXABLE | PARTIALLY_TAXABLE
    exemption_limit_monthly: float = 0.0
    exemption_limit_annual: float = 0.0

    pf_applicable: bool = False
    esi_applicable: bool = True
    pt_applicable: bool = True
    lwf_applicable: bool = False

    included_in_ctc: bool = True
    included_in_gross: bool = True
    included_in_net: bool = True
    appears_on_payslip: bool = True

    is_mandatory: bool = False
    is_active: bool = True
    display_order: int = 1

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AllowanceCreateSchema(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    display_name: Optional[str] = None
    code: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = None
    category: str = "SPECIAL"

    earning_type: str = "FIXED"
    is_variable: Optional[bool] = False
    frequency: Optional[str] = "MONTHLY"
    is_recurring: Optional[bool] = True

    calc_type: str = "FIXED"
    formula_expr: Optional[str] = None
    default_amount: Optional[float] = 0.0
    min_limit: Optional[float] = 0.0
    max_limit: Optional[float] = 0.0
    currency: Optional[str] = "INR"

    taxability_type: str = "TAXABLE"
    exemption_limit_monthly: Optional[float] = 0.0
    exemption_limit_annual: Optional[float] = 0.0

    pf_applicable: Optional[bool] = False
    esi_applicable: Optional[bool] = True
    pt_applicable: Optional[bool] = True
    lwf_applicable: Optional[bool] = False

    included_in_ctc: Optional[bool] = True
    included_in_gross: Optional[bool] = True
    included_in_net: Optional[bool] = True
    appears_on_payslip: Optional[bool] = True

    is_mandatory: Optional[bool] = False
    is_active: Optional[bool] = True
    display_order: Optional[int] = 1

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.match(r"^[A-Z0-9_]{2,50}$", v):
            raise ValueError("Allowance code must contain uppercase letters, numbers, or underscores (e.g. ALLOWANCE_HRA)")
        return v


class AllowanceUpdateSchema(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    earning_type: Optional[str] = None
    is_variable: Optional[bool] = None
    frequency: Optional[str] = None
    calc_type: Optional[str] = None
    formula_expr: Optional[str] = None
    default_amount: Optional[float] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    currency: Optional[str] = None
    taxability_type: Optional[str] = None
    exemption_limit_monthly: Optional[float] = None
    exemption_limit_annual: Optional[float] = None
    pf_applicable: Optional[bool] = None
    esi_applicable: Optional[bool] = None
    pt_applicable: Optional[bool] = None
    included_in_ctc: Optional[bool] = None
    included_in_gross: Optional[bool] = None
    appears_on_payslip: Optional[bool] = None
    is_active: Optional[bool] = None
