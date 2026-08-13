"""Pydantic schemas for the Company Admin Onboarding Flow."""

from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field

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

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    company_name: str = Field(
        default="My Company",
        validation_alias=AliasChoices("company_name", "companyName", "name", "title"),
    )
    company_logo: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_logo", "companyLogo", "logo"),
    )
    industry: str | None = Field(default=None)
    company_size: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_size", "companySize", "size"),
    )
    country: str = Field(default="India")
    state: str | None = Field(default=None)
    city: str | None = Field(default=None)
    timezone: str = Field(default="Asia/Kolkata")
    currency: str = Field(default="INR")


class AdminProfileStepInput(BaseModel):
    """Payload for Step 2 — Admin Profile."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    first_name: str = Field(
        default="Admin",
        validation_alias=AliasChoices("first_name", "firstName", "name"),
    )
    last_name: str = Field(
        default="User",
        validation_alias=AliasChoices("last_name", "lastName"),
    )
    profile_photo: str | None = Field(
        default=None,
        validation_alias=AliasChoices("profile_photo", "profilePhoto", "photo"),
    )
    mobile_number: str = Field(
        default="",
        validation_alias=AliasChoices("mobile_number", "mobileNumber", "phone", "mobile"),
    )
    designation: str | None = Field(default=None)
    preferred_language: str | None = Field(
        default="English",
        validation_alias=AliasChoices("preferred_language", "preferredLanguage", "language"),
    )


class HRSettingsStepInput(BaseModel):
    """Payload for Step 3 — HR Setup."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    working_days: list[str] = Field(
        default=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        validation_alias=AliasChoices("working_days", "workingDays"),
    )
    week_start_day: str = Field(
        default="Monday",
        validation_alias=AliasChoices("week_start_day", "weekStartDay"),
    )
    office_timing: str = Field(
        default="09:00 AM - 06:00 PM",
        validation_alias=AliasChoices("office_timing", "officeTiming", "timing"),
    )
    default_shift: str = Field(
        default="General",
        validation_alias=AliasChoices("default_shift", "defaultShift", "shift"),
    )
    time_format: str = Field(
        default="12h",
        validation_alias=AliasChoices("time_format", "timeFormat"),
    )
    date_format: str = Field(
        default="DD/MM/YYYY",
        validation_alias=AliasChoices("date_format", "dateFormat"),
    )
    financial_year: str = Field(
        default="April - March",
        validation_alias=AliasChoices("financial_year", "financialYear"),
    )
    leave_policy_template: str = Field(
        default="Standard",
        validation_alias=AliasChoices("leave_policy_template", "leavePolicyTemplate"),
    )


class DepartmentStepInput(BaseModel):
    """Payload for individual department creation."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    department_code: str = Field(
        default="",
        validation_alias=AliasChoices("department_code", "departmentCode", "code"),
    )
    department_name: str = Field(
        default="",
        validation_alias=AliasChoices("department_name", "departmentName", "name"),
    )
    description: str = Field(default="")


class DepartmentStepInputList(BaseModel):
    """Payload for Step 4 — Departments Setup."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    departments: list[DepartmentStepInput] = Field(default=[])


class DesignationStepInputList(BaseModel):
    """Payload for Step 4 — Designations Setup."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    designations: list[str] = Field(default=[])


class InviteEmployeeStepInput(BaseModel):
    """Payload for individual employee invitation."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    first_name: str = Field(
        default="",
        validation_alias=AliasChoices("first_name", "firstName"),
    )
    last_name: str = Field(
        default="",
        validation_alias=AliasChoices("last_name", "lastName"),
    )
    personal_email: str = Field(
        default="",
        validation_alias=AliasChoices("personal_email", "personalEmail", "email"),
    )
    phone: str = Field(
        default="",
        validation_alias=AliasChoices("phone", "mobile", "mobile_number"),
    )
    department: str = Field(default="")
    designation: str = Field(default="")


class InviteEmployeeStepInputList(BaseModel):
    """Payload for Step 5 — Invite Employees."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    employees: list[InviteEmployeeStepInput] = Field(default=[])
    skip: bool = False
