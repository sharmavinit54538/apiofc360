"""Pydantic schemas and validation for Payroll Settings."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class PTSlabSchema(BaseModel):
    upto: Optional[float] = None
    amount: float = 0.0


class PayrollSettingsSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    company_name: str = "Aurix AI Enterprise"
    legal_business_name: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    tan_number: Optional[str] = None
    cin_number: Optional[str] = None
    state: Optional[str] = "Telangana"
    currency: str = "INR"
    country: str = "India"
    timezone: str = "Asia/Kolkata"
    financial_year_start: str = "04-01"
    payroll_start_day: int = 1
    payroll_end_day: int = 30
    salary_payment_date: int = 1
    working_days_policy: Optional[str] = "EXCLUDE_WEEKENDS"
    salary_calc_method: Optional[str] = "MONTHLY_FIXED"
    attendance_source: Optional[str] = "FACE_BIOMETRIC"
    payslip_footer: Optional[str] = "Confidential Payroll Document — Aurix Enterprise"
    company_logo_url: Optional[str] = None
    digital_signature_url: Optional[str] = None
    approval_levels: int = 2
    auto_lock_payroll: bool = True
    enable_draft_payroll: bool = True
    enable_retro_payroll: bool = True

    pay_cycle_type: str = "MONTHLY"
    grace_period_days: int = 3
    cutoff_date: int = 25
    preview_days: int = 5

    pf_enabled: bool = True
    employee_pf_rate: float = 0.12
    employer_pf_rate: float = 0.12
    pf_wage_ceiling: float = 15000.00
    pf_on_full_basic: bool = False

    esi_enabled: bool = True
    employee_esi_rate: float = 0.0075
    employer_esi_rate: float = 0.0325
    esi_wage_ceiling: float = 21000.00

    pt_state: str = "TELANGANA"
    pt_slabs: List[PTSlabSchema] = Field(default_factory=list)
    default_tax_regime: str = "NEW"
    lop_basis: str = "CALENDAR_DAYS"

    overtime_enabled: bool = True
    overtime_multiplier_holiday: float = 2.0
    overtime_multiplier_weekend: float = 1.5
    overtime_multiplier_night: float = 1.25

    bank_name: str = "HDFC Bank"
    bank_ifsc: str = "HDFC0001234"
    salary_transfer_format: str = "NEFT"
    auto_email_payslips: bool = True
    auto_backup_payroll: bool = True

    settings_data: Optional[Dict[str, Any]] = None
    effective_from: Optional[str] = None
    is_active: bool = True

    @field_validator("gst_number")
    @classmethod
    def validate_gst(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        v = v.strip().upper()
        pattern = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid GST Number format (e.g. 36AAACA1234A1Z5)")
        return v

    @field_validator("pan_number")
    @classmethod
    def validate_pan(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        v = v.strip().upper()
        pattern = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid PAN Number format (e.g. ABCDE1234F)")
        return v

    @field_validator("tan_number")
    @classmethod
    def validate_tan(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        v = v.strip().upper()
        pattern = r"^[A-Z]{4}[0-9]{5}[A-Z]{1}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid TAN Number format (e.g. ABCD12345E)")
        return v

    @field_validator("cin_number")
    @classmethod
    def validate_cin(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        v = v.strip().upper()
        pattern = r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$"
        if not re.match(pattern, v):
            raise ValueError("Invalid CIN Number format (e.g. L12345TG2026PLC123456)")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        valid_currencies = {"INR", "USD", "EUR", "GBP", "AED", "SGD", "CAD", "AUD"}
        v_clean = v.split()[0].upper() if " " in v else v.upper()
        if v_clean not in valid_currencies:
            return "INR"
        return v_clean


class PayrollSettingsUpdateSchema(BaseModel):
    company_name: Optional[str] = None
    legal_business_name: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    tan_number: Optional[str] = None
    cin_number: Optional[str] = None
    state: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    financial_year_start: Optional[str] = None
    payroll_start_day: Optional[int] = None
    payroll_end_day: Optional[int] = None
    salary_payment_date: Optional[int] = None
    working_days_policy: Optional[str] = None
    salary_calc_method: Optional[str] = None
    attendance_source: Optional[str] = None
    payslip_footer: Optional[str] = None
    company_logo_url: Optional[str] = None
    digital_signature_url: Optional[str] = None
    approval_levels: Optional[int] = None
    auto_lock_payroll: Optional[bool] = None
    enable_draft_payroll: Optional[bool] = None
    enable_retro_payroll: Optional[bool] = None
    pay_cycle_type: Optional[str] = None
    grace_period_days: Optional[int] = None
    cutoff_date: Optional[int] = None
    preview_days: Optional[int] = None
    pf_enabled: Optional[bool] = None
    employee_pf_rate: Optional[float] = None
    employer_pf_rate: Optional[float] = None
    pf_wage_ceiling: Optional[float] = None
    pf_on_full_basic: Optional[bool] = None
    esi_enabled: Optional[bool] = None
    employee_esi_rate: Optional[float] = None
    employer_esi_rate: Optional[float] = None
    esi_wage_ceiling: Optional[float] = None
    pt_state: Optional[str] = None
    pt_slabs: Optional[List[PTSlabSchema]] = None
    default_tax_regime: Optional[str] = None
    lop_basis: Optional[str] = None
    overtime_enabled: Optional[bool] = None
    overtime_multiplier_holiday: Optional[float] = None
    overtime_multiplier_weekend: Optional[float] = None
    overtime_multiplier_night: Optional[float] = None
    bank_name: Optional[str] = None
    bank_ifsc: Optional[str] = None
    salary_transfer_format: Optional[str] = None
    auto_email_payslips: Optional[bool] = None
    auto_backup_payroll: Optional[bool] = None
    settings_data: Optional[Dict[str, Any]] = None
    reason: Optional[str] = "Updated payroll configuration settings"


class PayrollSettingsHistorySchema(BaseModel):
    id: str
    version_number: int
    config_data: Dict[str, Any]
    changed_by: Optional[str] = None
    change_reason: Optional[str] = None
    effective_from: str
    is_active: bool
    created_at: str


class SettingsResetPayload(BaseModel):
    reason: Optional[str] = "Reset settings to default compliance presets"
