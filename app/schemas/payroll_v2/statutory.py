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


class StatutorySummaryResponse(PayrollBaseModel):
    component: str
    period_id: str
    total_employees: int = 0
    employee_contribution_paise: int = 0
    employer_contribution_paise: int = 0
    total_liability_paise: int = 0
    breakup: Optional[List[dict[str, Any]]] = None
