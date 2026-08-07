"""Pydantic schemas and validation for Salary Components & Calculation Engine."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class SalaryComponentSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    name: str
    code: str
    component_type: str = "EARNING"
    category: str = "BASIC"
    description: Optional[str] = None
    display_name: Optional[str] = None
    payroll_code: Optional[str] = None
    display_order: int = 1

    calc_type: str = "FIXED"
    formula_expr: Optional[str] = None
    fixed_amount: float = 0.0
    percentage_value: float = 0.0

    is_system: bool = False
    is_mandatory: bool = False
    is_taxable: bool = True
    pf_applicable: bool = True
    esi_applicable: bool = True
    pt_applicable: bool = True
    included_in_ctc: bool = True
    included_in_gross: bool = True
    included_in_net: bool = True
    appears_on_payslip: bool = True
    employee_editable: bool = False
    hr_editable: bool = True

    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SalaryComponentCreateSchema(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    code: str = Field(..., min_length=2, max_length=50)
    component_type: str = "EARNING"
    category: str = "BASIC"
    description: Optional[str] = None
    display_name: Optional[str] = None
    payroll_code: Optional[str] = None
    display_order: Optional[int] = 1

    calc_type: str = "FIXED"
    formula_expr: Optional[str] = None
    fixed_amount: Optional[float] = 0.0
    percentage_value: Optional[float] = 0.0

    is_mandatory: Optional[bool] = False
    is_taxable: Optional[bool] = True
    pf_applicable: Optional[bool] = True
    esi_applicable: Optional[bool] = True
    pt_applicable: Optional[bool] = True
    included_in_ctc: Optional[bool] = True
    included_in_gross: Optional[bool] = True
    included_in_net: Optional[bool] = True
    appears_on_payslip: Optional[bool] = True
    is_active: Optional[bool] = True

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.match(r"^[A-Z0-9_]{2,50}$", v):
            raise ValueError("Component code must contain uppercase letters, numbers, or underscores (e.g. BASIC_SALARY)")
        return v


class SalaryComponentUpdateSchema(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    component_type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    display_name: Optional[str] = None
    payroll_code: Optional[str] = None
    display_order: Optional[int] = None
    calc_type: Optional[str] = None
    formula_expr: Optional[str] = None
    fixed_amount: Optional[float] = None
    percentage_value: Optional[float] = None
    is_taxable: Optional[bool] = None
    pf_applicable: Optional[bool] = None
    esi_applicable: Optional[bool] = None
    pt_applicable: Optional[bool] = None
    included_in_ctc: Optional[bool] = None
    included_in_gross: Optional[bool] = None
    included_in_net: Optional[bool] = None
    appears_on_payslip: Optional[bool] = None
    is_active: Optional[bool] = None


class ReorderItemSchema(BaseModel):
    id: str
    display_order: int


class ReorderPayloadSchema(BaseModel):
    items: List[ReorderItemSchema]
