"""Pydantic schemas for Employee-facing Payroll and Bank Accounts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import Field

from app.schemas.payroll_v2.common import PayrollBaseModel


class RevealBankAccountRequest(PayrollBaseModel):
    reason: str = Field(..., min_length=2, description="Justification for accessing masked bank details")


class BankAccountRevealedResponse(PayrollBaseModel):
    employee_id: str
    bank_name: str
    account_number: str
    ifsc_code: str
    account_holder_name: str


class EmployeeDashboardResponse(PayrollBaseModel):
    employee_id: str
    current_ctc_annual_paise: int = 0
    latest_net_pay_paise: int = 0
    recent_payslips: List[dict[str, Any]] = Field(default_factory=list)
    pending_reimbursements_count: int = 0
    tax_regime: str = "NEW"


class ProvisionSlipResponse(PayrollBaseModel):
    id: str
    slip_number: str
    employee_id: str
    period_month: int
    period_year: int
    gross_earnings_paise: int
    total_deductions_paise: int
    net_pay_paise: int
    status: str
    pdf_path: Optional[str] = None
    breakup: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class PayslipDetailResponse(PayrollBaseModel):
    id: str
    payslip_number: str
    employee_id: str
    employee_name: Optional[str] = None
    period_month: int
    period_year: int
    paid_days: float
    lop_days: float
    gross_earnings: float
    total_deductions: float
    net_pay: float
    gross_earnings_paise: int = 0
    total_deductions_paise: int = 0
    net_pay_paise: int = 0
    earnings_breakup: Optional[dict[str, Any]] = None
    deductions_breakup: Optional[dict[str, Any]] = None
    payment_status: str
    pdf_path: Optional[str] = None
    created_at: Optional[datetime] = None


class CompanyBankAccountResponse(PayrollBaseModel):
    id: str
    company_id: str
    bank_name: str
    account_number: str
    ifsc_code: str
    account_holder_name: str
    account_type: str
    is_primary: bool
    is_active: bool
