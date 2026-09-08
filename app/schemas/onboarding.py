"""Pydantic schemas for the HR Admin Onboarding Flow.

Production-ready schemas supporting all 6 onboarding stages:
1. Admin Profile
2. Company Setup
3. Organization & Departments
4. Work Schedule & Leave Policies
5. Employee Invitations (Individual Only)
6. Review & Activate
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
import uuid

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────────────
# API Response Envelopes
# ─────────────────────────────────────────────────────────────────────────────

class APIErrorDetail(BaseModel):
    """Detailed error object matching the required API contract."""
    code: str
    message: str
    fields: dict[str, Any] = {}


class OnboardingAPIResponse(BaseModel, Generic[T]):
    """Standardized onboarding API response envelope."""

    success: bool
    message: str
    data: T
    current_step: int | None = None
    onboarding_completed: bool | None = None
    redirect_step: int | None = None
    error: APIErrorDetail | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Admin Profile Schemas
# ─────────────────────────────────────────────────────────────────────────────

class HRAdminProfileInput(BaseModel):
    """Payload to create or update HR Admin Profile."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    first_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("first_name", "firstName", "name"),
        description="Admin first name",
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("last_name", "lastName"),
        description="Admin last name",
    )
    work_email: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices("work_email", "workEmail", "email"),
        description="Admin work email",
    )
    phone_number: str = Field(
        ...,
        min_length=7,
        max_length=20,
        validation_alias=AliasChoices("phone_number", "phoneNumber", "phone", "mobile", "mobile_number", "mobileNumber"),
        description="Contact phone number",
    )
    job_title: str | None = Field(
        default="HR Admin",
        max_length=100,
        validation_alias=AliasChoices("job_title", "jobTitle", "designation", "role_title"),
        description="Job title / Designation",
    )
    profile_photo_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("profile_photo_url", "profilePhotoUrl", "profile_photo", "profilePhoto", "photo", "avatar"),
        description="Profile photo URL",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        clean = "".join(ch for ch in str(v).strip() if ch.isdigit() or ch in "+ -()")
        digits = "".join(filter(str.isdigit, clean))
        if len(digits) < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return clean


class HRAdminProfileResponse(BaseModel):
    """Response containing HR Admin Profile data."""

    first_name: str
    last_name: str
    work_email: str
    phone_number: str
    job_title: str
    profile_photo_url: str | None = None
    organization_id: str | None = None


# Compatibility alias for existing codebase
AdminProfileStepInput = HRAdminProfileInput


# ─────────────────────────────────────────────────────────────────────────────
# 2. Organization / Company Schemas
# ─────────────────────────────────────────────────────────────────────────────

class OrganizationInput(BaseModel):
    """Payload to create or update Company / Organization data."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    company_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        validation_alias=AliasChoices("company_name", "companyName", "name", "title"),
        description="Company / Organization name",
    )
    industry: str | None = Field(default=None, max_length=100)
    company_size: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_size", "companySize", "size"),
    )
    website: str | None = Field(default=None, max_length=255)
    country: str = Field(default="India", max_length=100)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    zip_code: str | None = Field(
        default=None,
        max_length=20,
        validation_alias=AliasChoices("zip_code", "zipCode", "postal_code", "postalCode", "pinCode"),
    )
    cin: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("cin", "cin_number", "cinNumber"),
    )
    gst_number: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("gst_number", "gstNumber", "gst"),
    )
    company_logo_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_logo_url", "companyLogoUrl", "company_logo", "companyLogo", "logo"),
    )
    company_stamp_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_stamp_url", "companyStampUrl", "company_stamp", "companyStamp", "stamp"),
    )


class OrganizationResponse(BaseModel):
    """Response containing Organization details."""

    id: str
    company_name: str
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    country: str = "India"
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    cin: str | None = None
    gst_number: str | None = None
    company_logo_url: str | None = None
    company_stamp_url: str | None = None
    status: str = "PENDING"
    onboarding_completed: bool = False


# Compatibility alias for existing codebase
CompanyStepInput = OrganizationInput


# ─────────────────────────────────────────────────────────────────────────────
# 3. Department Schemas
# ─────────────────────────────────────────────────────────────────────────────

class DepartmentCreateInput(BaseModel):
    """Payload to create a single department."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    department_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("department_name", "departmentName", "name"),
    )
    department_code: str | None = Field(
        default=None,
        max_length=30,
        validation_alias=AliasChoices("department_code", "departmentCode", "code"),
    )
    description: str | None = Field(default="", max_length=1000)
    location: str | None = Field(default="Headquarters", max_length=100)


class DepartmentUpdateInput(BaseModel):
    """Payload to update an existing department."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    department_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("department_name", "departmentName", "name"),
    )
    department_code: str | None = Field(
        default=None,
        max_length=30,
        validation_alias=AliasChoices("department_code", "departmentCode", "code"),
    )
    description: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=20)


class DepartmentItemResponse(BaseModel):
    """Department item representation."""

    id: str
    company_id: str
    department_name: str
    department_code: str
    description: str | None = None
    location: str = "Headquarters"
    status: str = "ACTIVE"
    employee_count: int = 0
    created_at: str | None = None


# Compatibility aliases for existing batch step endpoint
class DepartmentStepInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    department_code: str = Field(default="", validation_alias=AliasChoices("department_code", "departmentCode", "code"))
    department_name: str = Field(default="", validation_alias=AliasChoices("department_name", "departmentName", "name"))
    description: str = Field(default="")


class DepartmentStepInputList(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    departments: list[DepartmentStepInput] = Field(default=[])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Designation Schemas
# ─────────────────────────────────────────────────────────────────────────────

class DesignationCreateInput(BaseModel):
    """Payload to create a designation."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "designation_name", "designationName", "title"),
    )
    description: str | None = Field(default=None, max_length=255)


class DesignationUpdateInput(BaseModel):
    """Payload to update a designation."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "designation_name", "designationName", "title"),
    )
    description: str | None = Field(default=None, max_length=255)


class DesignationItemResponse(BaseModel):
    """Designation item representation."""

    id: str
    company_id: str
    name: str
    description: str | None = None
    created_at: str | None = None


# Compatibility aliases for batch step
class DesignationStepInputList(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    designations: list[str] = Field(default=[])


# ─────────────────────────────────────────────────────────────────────────────
# 5. Work Schedule & HR Settings Schemas
# ─────────────────────────────────────────────────────────────────────────────

VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


class WorkScheduleInput(BaseModel):
    """Payload for Work Schedule and HR Settings configuration."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    timezone: str = Field(
        default="Asia/Kolkata",
        max_length=50,
        validation_alias=AliasChoices("timezone", "time_zone", "timeZone"),
    )
    currency: str = Field(
        default="INR",
        max_length=10,
        validation_alias=AliasChoices("currency", "currencyCode"),
    )
    date_format: str = Field(
        default="YYYY-MM-DD",
        max_length=20,
        validation_alias=AliasChoices("date_format", "dateFormat"),
    )
    time_format: str = Field(
        default="12h",
        max_length=20,
        validation_alias=AliasChoices("time_format", "timeFormat"),
    )
    financial_year: str = Field(
        default="2026-2027",
        max_length=30,
        validation_alias=AliasChoices("financial_year", "financialYear"),
    )
    week_start_day: str = Field(
        default="Monday",
        max_length=20,
        validation_alias=AliasChoices("week_start_day", "weekStartDay"),
    )
    working_days: list[str] = Field(
        default=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        validation_alias=AliasChoices("working_days", "workingDays"),
    )
    office_start_time: str = Field(
        default="09:00",
        max_length=10,
        validation_alias=AliasChoices("office_start_time", "officeStartTime", "start_time", "startTime"),
    )
    office_end_time: str = Field(
        default="18:00",
        max_length=10,
        validation_alias=AliasChoices("office_end_time", "officeEndTime", "end_time", "endTime"),
    )
    default_shift: str = Field(
        default="General Shift",
        max_length=50,
        validation_alias=AliasChoices("default_shift", "defaultShift", "shift"),
    )

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, v: list[str]) -> list[str]:
        if not v or len(v) == 0:
            raise ValueError("At least one working day must be selected.")
        normalized = []
        for d in v:
            clean = str(d).strip().capitalize()
            if clean not in VALID_DAYS:
                raise ValueError(f"Invalid weekday: {d}. Must be one of {sorted(VALID_DAYS)}.")
            normalized.append(clean)
        return normalized

    @field_validator("office_start_time", "office_end_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        clean = str(v).strip()
        # Accept HH:MM (24h) or "09:00 AM"
        if not clean:
            raise ValueError("Time string cannot be empty.")
        return clean


class WorkScheduleResponse(BaseModel):
    """Response containing Work Schedule and HR Settings."""

    timezone: str
    currency: str
    date_format: str
    time_format: str
    financial_year: str
    week_start_day: str
    working_days: list[str]
    office_start_time: str
    office_end_time: str
    default_shift: str


# Compatibility alias
HRSettingsStepInput = WorkScheduleInput


# ─────────────────────────────────────────────────────────────────────────────
# 6. Leave Policy Schemas
# ─────────────────────────────────────────────────────────────────────────────

class LeavePolicyCreateInput(BaseModel):
    """Payload to create a leave policy."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "policy_name", "policyName"),
    )
    leave_type: str = Field(
        default="ANNUAL",
        max_length=50,
        validation_alias=AliasChoices("leave_type", "leaveType", "type"),
    )
    days_allowed: float = Field(
        ...,
        gt=0,
        le=365,
        validation_alias=AliasChoices("days_allowed", "daysAllowed", "days", "number_of_days", "numberOfDays"),
    )
    description: str | None = Field(default="", max_length=255)
    status: str = Field(default="ACTIVE", max_length=20)


class LeavePolicyUpdateInput(BaseModel):
    """Payload to update a leave policy."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "policy_name", "policyName"),
    )
    leave_type: str | None = Field(default=None, max_length=50, validation_alias=AliasChoices("leave_type", "leaveType"))
    days_allowed: float | None = Field(
        default=None,
        gt=0,
        le=365,
        validation_alias=AliasChoices("days_allowed", "daysAllowed", "days", "number_of_days"),
    )
    description: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=20)


class LeavePolicyResponse(BaseModel):
    """Leave policy item representation."""

    id: str
    company_id: str
    name: str
    leave_type: str
    days_allowed: float
    description: str | None = None
    status: str = "ACTIVE"
    created_at: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Individual Employee Invitation Schemas (STRICTLY INDIVIDUAL ONLY)
# ─────────────────────────────────────────────────────────────────────────────

class IndividualInvitationInput(BaseModel):
    """Payload for individual employee invitation. Bulk APIs strictly prohibited."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    employee_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("employee_name", "employeeName", "name", "fullName"),
    )
    employee_email: EmailStr = Field(
        ...,
        validation_alias=AliasChoices("employee_email", "employeeEmail", "email", "personal_email", "personalEmail"),
    )
    department: str | None = Field(default=None, max_length=100)
    designation: str | None = Field(default=None, max_length=100)


class InvitationResponse(BaseModel):
    """Response representing an employee invitation."""

    id: str
    company_id: str
    employee_name: str
    employee_email: str
    department: str | None = None
    designation: str | None = None
    invitation_token: str
    status: str = "PENDING"
    expires_at: str
    created_at: str


class InvitationListResponse(BaseModel):
    """List of pending employee invitations."""

    items: list[InvitationResponse]
    total: int


# Compatibility aliases for batch step
class InviteEmployeeStepInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    first_name: str = Field(default="", validation_alias=AliasChoices("first_name", "firstName"))
    last_name: str = Field(default="", validation_alias=AliasChoices("last_name", "lastName"))
    personal_email: str = Field(default="", validation_alias=AliasChoices("personal_email", "personalEmail", "email"))
    phone: str = Field(default="", validation_alias=AliasChoices("phone", "mobile"))
    department: str = Field(default="")
    designation: str = Field(default="")


class InviteEmployeeStepInputList(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    employees: list[InviteEmployeeStepInput] = Field(default=[])
    skip: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# 8. Onboarding Progress & Structure Review Schemas
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingProgressUpdateInput(BaseModel):
    """Payload to save onboarding progress."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    current_step: int = Field(..., ge=1, le=7)
    completed_steps: list[int | str] | None = None
    status: str | None = None


class OnboardingStatusResponse(BaseModel):
    """Payload for onboarding status endpoint."""

    onboarding_completed: bool
    current_step: int
    completion_percentage: float
    status: str = "in_progress"  # not_started, in_progress, completed
    started_at: str | None = None
    completed_at: str | None = None
    last_updated_at: str | None = None
    company_completed: bool = False
    admin_completed: bool = False
    hr_completed: bool = False
    departments_completed: bool = False
    designations_completed: bool = False
    employees_invited: bool = False


class OnboardingProgressResponse(BaseModel):
    """Comprehensive payload returning all saved onboarding progress data."""

    onboarding_completed: bool
    current_step: int
    status: str = "in_progress"
    started_at: str | None = None
    completed_at: str | None = None
    last_updated_at: str | None = None
    company_profile: dict[str, Any] | None = None
    hr_settings: dict[str, Any] | None = None
    admin_profile: dict[str, Any] | None = None
    departments: list[dict[str, Any]] = []
    designations: list[dict[str, Any]] = []
    shifts: list[dict[str, Any]] = []
    leave_policies: list[dict[str, Any]] = []
    pending_invitations: list[dict[str, Any]] = []
    step_flags: dict[str, bool] = {}


class OnboardingReviewResponse(BaseModel):
    """Aggregated organization structure for Review & Activate screen (Step 6)."""

    organization: dict[str, Any]
    admin_profile: dict[str, Any]
    departments: list[dict[str, Any]]
    designations: list[dict[str, Any]]
    work_schedule: dict[str, Any]
    leave_policies: list[dict[str, Any]]
    pending_invitations: list[dict[str, Any]]
    onboarding_status: str
    current_step: int
    completion_percentage: float


class FileUploadResponse(BaseModel):
    """Response returned when an asset file is uploaded."""

    url: str
    filename: str
    size: int
    category: str
