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
