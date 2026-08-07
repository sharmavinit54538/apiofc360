"""Pydantic schemas and validation for Enterprise Overtime Management System."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class PayrollOvertimeSettingSchema(BaseModel):
    id: Optional[str] = None
    company_id: Optional[str] = None
    overtime_enabled: bool = True
    overtime_code: str = "OT_POLICY_STD"
    calc_method: str = "HOURLY_MULTIPLIER"

    standard_multiplier: float = 1.5
    weekend_multiplier: float = 1.5
    holiday_multiplier: float = 2.0
    night_shift_multiplier: float = 1.25
    emergency_multiplier: float = 2.5

    min_hours_per_day: float = 1.0
    max_hours_per_day: float = 4.0
    max_hours_per_week: float = 16.0
    max_hours_per_month: float = 50.0

    auto_approval_enabled: bool = False
    auto_approval_threshold_hours: float = 2.0
    require_manager_approval: bool = True

    comp_off_enabled: bool = True
    comp_off_expiry_days: int = 90

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PayrollOvertimeUpdateSchema(BaseModel):
    overtime_enabled: Optional[bool] = None
    overtime_code: Optional[str] = None
    calc_method: Optional[str] = None
    standard_multiplier: Optional[float] = None
    weekend_multiplier: Optional[float] = None
    holiday_multiplier: Optional[float] = None
    night_shift_multiplier: Optional[float] = None
    emergency_multiplier: Optional[float] = None
    min_hours_per_day: Optional[float] = None
    max_hours_per_day: Optional[float] = None
    max_hours_per_week: Optional[float] = None
    max_hours_per_month: Optional[float] = None
    auto_approval_enabled: Optional[bool] = None
    auto_approval_threshold_hours: Optional[float] = None
    comp_off_enabled: Optional[bool] = None
    comp_off_expiry_days: Optional[int] = None

    @model_validator(mode="after")
    def validate_caps(self) -> PayrollOvertimeUpdateSchema:
        if self.min_hours_per_day is not None and self.max_hours_per_day is not None:
            if self.min_hours_per_day > self.max_hours_per_day:
                raise ValueError("Minimum OT hours per day cannot be greater than Maximum daily OT cap.")
        return self


class CalculateOvertimeSchema(BaseModel):
    basic_salary: float = Field(..., ge=0)
    overtime_hours: float = Field(..., ge=0)
    ot_type: str = "STANDARD"  # STANDARD | WEEKEND | HOLIDAY | NIGHT_SHIFT | EMERGENCY
    working_days_in_month: Optional[int] = 26
    working_hours_per_day: Optional[int] = 8
