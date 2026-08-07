"""Pydantic schemas and validation for Enterprise Payroll Compliance Management System."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class PayrollComplianceSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    compliance_name: str
    compliance_code: str
    category: str = "EPF"
    description: Optional[str] = None
    financial_year: str = "2026-2027"
    state: Optional[str] = "ALL_INDIA"
    status: str = "COMPLIANT"
    filing_frequency: str = "MONTHLY"
    due_day_of_month: int = 15
    is_enabled: bool = True
    auto_file: bool = False
    auto_remind: bool = True
    compliance_score: int = 100
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PayrollComplianceCreateSchema(BaseModel):
    compliance_name: str = Field(..., min_length=2, max_length=100)
    compliance_code: str = Field(..., min_length=2, max_length=50)
    category: str = "EPF"
    description: Optional[str] = None
    financial_year: Optional[str] = "2026-2027"
    state: Optional[str] = "ALL_INDIA"
    status: Optional[str] = "COMPLIANT"
    filing_frequency: Optional[str] = "MONTHLY"
    due_day_of_month: Optional[int] = 15
    is_enabled: Optional[bool] = True
    auto_file: Optional[bool] = False
    auto_remind: Optional[bool] = True

    @field_validator("compliance_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.match(r"^[A-Z0-9_]{2,50}$", v):
            raise ValueError("Compliance code must contain uppercase letters, numbers, or underscores (e.g. COMP_EPF_ECR)")
        return v


class PayrollComplianceUpdateSchema(BaseModel):
    compliance_name: Optional[str] = None
    compliance_code: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    financial_year: Optional[str] = None
    state: Optional[str] = None
    status: Optional[str] = None
    filing_frequency: Optional[str] = None
    due_day_of_month: Optional[int] = None
    is_enabled: Optional[bool] = None
    auto_file: Optional[bool] = None
    auto_remind: Optional[bool] = None


class GenerateChallanSchema(BaseModel):
    challan_type: str = "EPFO_ECR"  # EPFO_ECR | ESIC_CHALLAN | PT_CHALLAN | TDS_CHALLAN
    period_month: int = Field(7, ge=1, le=12)
    period_year: int = Field(2026, ge=2020, le=2050)


class ValidateComplianceSchema(BaseModel):
    financial_year: Optional[str] = "2026-2027"
