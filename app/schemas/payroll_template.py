"""Pydantic schemas and validation for Enterprise Payroll Template Management System."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class PayrollTemplateSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    template_name: str
    template_code: str
    category: str = "PAYSLIP"
    description: Optional[str] = None
    doc_format: str = "PDF"
    language: str = "EN"
    status: str = "PUBLISHED"
    version_number: int = 1
    is_default: bool = False
    styling_theme: str = "MODERN_DARK"
    html_content: str
    header_logo_url: Optional[str] = None
    footer_text: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PayrollTemplateCreateSchema(BaseModel):
    template_name: str = Field(..., min_length=2, max_length=100)
    template_code: str = Field(..., min_length=2, max_length=50)
    category: str = "PAYSLIP"
    description: Optional[str] = None
    doc_format: Optional[str] = "PDF"
    language: Optional[str] = "EN"
    status: Optional[str] = "PUBLISHED"
    is_default: Optional[bool] = False
    styling_theme: Optional[str] = "MODERN_DARK"
    html_content: str = Field(..., min_length=10)
    header_logo_url: Optional[str] = None
    footer_text: Optional[str] = None

    @field_validator("template_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.match(r"^[A-Z0-9_]{2,50}$", v):
            raise ValueError("Template code must contain uppercase letters, numbers, or underscores (e.g. TMPL_PAYSLIP_DARK)")
        return v


class PayrollTemplateUpdateSchema(BaseModel):
    template_name: Optional[str] = None
    template_code: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    doc_format: Optional[str] = None
    language: Optional[str] = None
    status: Optional[str] = None
    is_default: Optional[bool] = None
    styling_theme: Optional[str] = None
    html_content: Optional[str] = None
    header_logo_url: Optional[str] = None
    footer_text: Optional[str] = None


class GenerateDocumentSchema(BaseModel):
    template_id: str
    employee_name: Optional[str] = "Ramesh Kumar"
    employee_id: Optional[str] = "EMP-1004"
    designation: Optional[str] = "Senior Software Engineer"
    department: Optional[str] = "Engineering"
    basic_salary: Optional[float] = 50000.0
    gross_salary: Optional[float] = 125000.0
    net_salary: Optional[float] = 108500.0
    bank_name: Optional[str] = "HDFC Bank"
    account_number: Optional[str] = "XXXXXXXX5819"


class PreviewTemplateSchema(BaseModel):
    html_content: str
    sample_data: Optional[Dict[str, Any]] = None
