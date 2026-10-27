"""Pydantic schemas for Statutory Compliance."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import Field, field_validator

from app.schemas.payroll_v2.common import PayrollBaseModel


ALLOWED_STATUTORY_COMPONENTS = ("PF", "ESI", "PT", "TDS")
ALLOWED_FORMATS = ("csv", "txt", "xlsx")


class StatutoryReportRequest(PayrollBaseModel):
    period_id: str = Field(..., alias="periodId")
    format: str = Field("csv")

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        clean = v.lower().strip()
        if clean not in ALLOWED_FORMATS:
            raise ValueError(f"format must be one of: {', '.join(ALLOWED_FORMATS)}")
        return clean


class StatutoryConfigResponse(PayrollBaseModel):
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
    default_tax_regime: str = "NEW"


class StatutoryConfigRequest(PayrollBaseModel):
    pf_enabled: Optional[bool] = Field(None, alias="pfEnabled")
    employee_pf_rate: Optional[float] = Field(None, alias="employeePfRate")
    employer_pf_rate: Optional[float] = Field(None, alias="employerPfRate")
    pf_wage_ceiling: Optional[float] = Field(None, alias="pfWageCeiling")
    pf_on_full_basic: Optional[bool] = Field(None, alias="pfOnFullBasic")
    esi_enabled: Optional[bool] = Field(None, alias="esiEnabled")
    employee_esi_rate: Optional[float] = Field(None, alias="employeeEsiRate")
    employer_esi_rate: Optional[float] = Field(None, alias="employerEsiRate")
    esi_wage_ceiling: Optional[float] = Field(None, alias="esiWageCeiling")
    pt_state: Optional[str] = Field(None, alias="ptState")
    default_tax_regime: Optional[str] = Field(None, alias="defaultTaxRegime")


#: Every ``needs_ca_validation_*`` flag a CA / payroll expert can sign off.
CA_VALIDATION_SCOPES = (
    "pf_rates",
    "esi_rates",
    "pt_slabs",
    "tds_slabs",
    "gratuity",
    "lwf",
    "labour_codes",
)


class StatutoryCaSignoffRequest(PayrollBaseModel):
    """Payload for the CA / payroll-expert validation sign-off."""

    certificate_ref: Optional[str] = Field(None, alias="certificateRef", max_length=100)
    formula_version: Optional[str] = Field(None, alias="formulaVersion", max_length=50)
    scopes: Optional[List[str]] = Field(
        None,
        description=(
            "Optional subset of validation scopes to clear. "
            "Defaults to every scope (pf_rates, esi_rates, pt_slabs, tds_slabs, "
            "gratuity, lwf, labour_codes)."
        ),
    )
    remarks: Optional[str] = Field(None, max_length=500)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        cleaned: List[str] = []
        for item in v:
            code = str(item).strip().lower()
            if code not in CA_VALIDATION_SCOPES:
                raise ValueError(
                    f"scope must be one of: {', '.join(CA_VALIDATION_SCOPES)}"
                )
            if code not in cleaned:
                cleaned.append(code)
        if not cleaned:
            raise ValueError("scopes cannot be an empty list; omit it to clear every scope.")
        return cleaned


class StatutorySimulationRequest(PayrollBaseModel):
    basic_monthly_paise: int = Field(2500000, alias="basicMonthlyPaise")
    hra_monthly_paise: int = Field(1000000, alias="hraMonthlyPaise")
    special_allowance_monthly_paise: int = Field(500000, alias="specialAllowanceMonthlyPaise")
    other_earnings_paise: int = Field(0, alias="otherEarningsPaise")
    paid_days: float = Field(30.0, alias="paidDays")
    total_days: float = Field(30.0, alias="totalDays")
    state: str = Field("MAHARASHTRA")
    month: int = Field(3)
    tax_regime: str = Field("NEW", alias="taxRegime")
    pf_on_full_basic: bool = Field(False, alias="pfOnFullBasic")
    declarations: Optional[dict[str, Any]] = None


class StatutorySummaryResponse(PayrollBaseModel):
    component: str
    period_id: str
    total_employees: int = 0
    employee_contribution_paise: int = 0
    employer_contribution_paise: int = 0
    total_liability_paise: int = 0
    breakup: Optional[List[dict[str, Any]]] = None


class ChallanRecordRequest(PayrollBaseModel):
    period_id: str = Field(..., alias="periodId")
    trrn_number: str = Field(..., alias="trrnNumber")
    challan_generation_date: Optional[str] = Field(None, alias="challanGenerationDate")
    payment_date: Optional[str] = Field(None, alias="paymentDate")
    utr_number: Optional[str] = Field(None, alias="utrNumber")
    total_amount: Optional[float] = Field(None, alias="totalAmount")
    epf_employee_amount: Optional[float] = Field(None, alias="epfEmployeeAmount")
    epf_employer_amount: Optional[float] = Field(None, alias="epfEmployerAmount")
    eps_amount: Optional[float] = Field(None, alias="epsAmount")
    edli_amount: Optional[float] = Field(None, alias="edliAmount")
    admin_charges: Optional[float] = Field(None, alias="adminCharges")


class EmployeePfUpdateRequest(PayrollBaseModel):
    uan_number: Optional[str] = Field(None, alias="uanNumber")
    is_pf_eligible: Optional[bool] = Field(None, alias="isPfEligible")
    is_international_worker: Optional[bool] = Field(None, alias="isInternationalWorker")
    pf_wage_ceiling_applicable: Optional[bool] = Field(None, alias="pfWageCeilingApplicable")


class UanValidationItem(PayrollBaseModel):
    employee_id: str
    employee_code: str
    name: str
    uan_number: Optional[str] = None
    is_valid: bool = False
    validation_error: Optional[str] = None
    is_pf_eligible: bool = True
    is_international_worker: bool = False
    pf_wage_ceiling_applicable: bool = True
    pan_number: Optional[str] = None
    basic_salary: float = 0.0
    gross_salary: float = 0.0


class UanValidationSummary(PayrollBaseModel):
    total_active_employees: int = 0
    valid_uan_count: int = 0
    invalid_uan_count: int = 0
    missing_uan_count: int = 0
    pf_opted_in_count: int = 0
    pf_opted_out_count: int = 0
    international_worker_count: int = 0
    employees: List[UanValidationItem] = []


class FilingCalendarItem(PayrollBaseModel):
    id: str
    month: int
    year: int
    wage_month_label: str
    due_date: str
    status: str
    trrn_number: Optional[str] = None
    payment_date: Optional[str] = None
    utr_number: Optional[str] = None
    total_amount: float = 0.0
    employee_count: int = 0
    is_overdue: bool = False
    overdue_days: int = 0
    interest_7q_amount: float = 0.0
    damages_14b_amount: float = 0.0
    damages_14b_rate_pct: float = 0.0
    challan_file_url: Optional[str] = None
    payment_receipt_url: Optional[str] = None


class PfEcrRecord(PayrollBaseModel):
    uan: str
    member_name: str
    gross_wages: float
    epf_wages: float
    eps_wages: float
    edli_wages: float
    ee_remitted: float
    eps_remitted: float
    er_diff_remitted: float
    ncp_days: int
    refund_advances: float = 0.0


class PfEcrResponse(PayrollBaseModel):
    period_id: str
    period_month: int
    period_year: int
    wage_month: str
    filename: str
    record_count: int
    total_gross: float
    total_epf_wages: float
    total_eps_wages: float
    total_ee_share: float
    total_eps_share: float
    total_er_diff_share: float
    total_edli_share: float
    admin_charges: float
    total_pf_liability: float
    records: List[PfEcrRecord]
    ecr_text: str
    has_missing_uan: bool
    missing_uan_count: int

