"""Pydantic schemas for the Company Admin Onboarding Flow."""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import BaseModel, EmailStr, Field

T = TypeVar("T")


class OnboardingAPIResponse(BaseModel, Generic[T]):
    """Standardized onboarding API response envelope."""

    success: bool
    message: str
    current_step: int
    onboarding_completed: bool
    data: T
    # Populated on 400/409 step-ordering violations so frontend can redirect automatically
    redirect_step: int | None = None


class OnboardingStatusResponse(BaseModel):
    """Payload for onboarding status endpoint."""

    onboarding_completed: bool
    current_step: int
    completion_percentage: float
    # Per-step completion flags
    company_completed: bool = False
    admin_completed: bool = False
    hr_completed: bool = False
    departments_completed: bool = False
    designations_completed: bool = False
    employees_invited: bool = False


class OnboardingProgressResponse(BaseModel):
    """Payload returning all saved onboarding progress data."""

    onboarding_completed: bool
    current_step: int
    company_profile: dict[str, Any] | None = None
    hr_settings: dict[str, Any] | None = None
    admin_profile: dict[str, Any] | None = None
    departments: list[dict[str, Any]] = []
    designations: list[dict[str, Any]] = []
    shifts: list[dict[str, Any]] = []
    leave_policies: list[dict[str, Any]] = []
    # Step completion flags so frontend knows which forms to prefill vs. skip
    step_flags: dict[str, bool] = {}



class CompanyStepInput(BaseModel):
    """Payload for Step 1 — Company Information."""

    company_name: str = Field(..., min_length=2, max_length=100)
    company_logo: str | None = None
    industry: str | None = None
    company_size: str | None = None
    country: str = Field(...)
    state: str | None = None
    city: str | None = None
    timezone: str = Field(...)
    currency: str = Field(...)


class AdminProfileStepInput(BaseModel):
    """Payload for Step 2 — Admin Profile."""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    profile_photo: str | None = None
    mobile_number: str = Field(..., min_length=10, max_length=15)
    designation: str | None = None
    preferred_language: str | None = None


class HRSettingsStepInput(BaseModel):
    """Payload for Step 3 — HR Setup."""

    working_days: list[str] = Field(...)
    week_start_day: str = Field(...)
    office_timing: str = Field(...)
    default_shift: str = Field(...)
    time_format: str = Field(...)
    date_format: str = Field(...)
    financial_year: str = Field(...)
    leave_policy_template: str = Field(...)


class DepartmentStepInput(BaseModel):
    """Payload for individual department creation."""

    department_code: str = Field(..., max_length=30)
    department_name: str = Field(..., max_length=100)
    description: str = Field(..., max_length=1000)


class DepartmentStepInputList(BaseModel):
    """Payload for Step 4 — Departments Setup."""

    departments: list[DepartmentStepInput] = Field(...)


class DesignationStepInputList(BaseModel):
    """Payload for Step 4 — Designations Setup."""

    designations: list[str] = Field(...)


class InviteEmployeeStepInput(BaseModel):
    """Payload for individual employee invitation."""

    first_name: str = Field(...)
    last_name: str = Field(...)
    personal_email: EmailStr = Field(...)
    phone: str = Field(..., min_length=10, max_length=15)
    department: str = Field(...)
    designation: str = Field(...)


class InviteEmployeeStepInputList(BaseModel):
    """Payload for Step 5 — Invite Employees."""

    employees: list[InviteEmployeeStepInput] = Field(default=[])
    skip: bool = False
